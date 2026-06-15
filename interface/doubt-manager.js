/**
 * DoubtManager - Handles all doubt-related functionality
 * Provides methods for showing doubts, asking new doubts, and managing doubt conversations
 */
const DoubtManager = {
    currentConversationId: null,
    currentMessageId: null,
    currentDoubtHistory: [],
    withContext: false,
    selectedText: '',
    
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
                this._sectionStates = data.section_states || {};
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
        
        // Sort: pinned first, then user-created, then auto-doubts (each group by date desc)
        const AUTO_DOUBT_TEXTS = ["Auto takeaways", "Maximize Learning and Perspectives", "Challenge & Verify", "Foundations & Practice", "Answer Raised Questions"];
        const isAuto = (d) => AUTO_DOUBT_TEXTS.some(t => d.doubt_text.startsWith(t));
        doubts.sort((a, b) => {
            const aPin = a.pinned ? 1 : 0, bPin = b.pinned ? 1 : 0;
            if (aPin !== bPin) return bPin - aPin;
            const aAuto = isAuto(a) ? 1 : 0, bAuto = isAuto(b) ? 1 : 0;
            if (aAuto !== bAuto) return aAuto - bAuto;
            return new Date(b.created_at) - new Date(a.created_at);
        });
        
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
        
        // Detect auto-doubts
        const AUTO_DOUBT_TEXTS = ["Auto takeaways", "Maximize Learning and Perspectives", "Challenge & Verify", "Foundations & Practice", "Answer Raised Questions"];
        const isAuto = AUTO_DOUBT_TEXTS.some(t => doubt.doubt_text.startsWith(t));
        const autoBadge = isAuto ? '<span class="badge badge-secondary ml-1">Auto</span>' : '';
        
        // Pin state
        const pinIcon = doubt.pinned ? 'bi-pin-fill' : 'bi-pin';
        const pinnedClass = doubt.pinned ? 'doubt-pinned' : '';
        
        // Bookmark count from children
        const bookmarkCount = (doubt.children || []).filter(c => c.bookmarked).length + (doubt.bookmarked ? 1 : 0);
        const bookmarkBadge = bookmarkCount > 0 ? `<span class="badge badge-warning ml-1">${bookmarkCount} <i class="bi bi-bookmark-fill"></i></span>` : '';
        
        const card = $(`
            <div class="card doubt-preview-card ${pinnedClass}" data-doubt-id="${doubt.doubt_id}">
                <div class="card-header d-flex justify-content-between align-items-center">
                    <span><strong>Doubt:</strong> ${createdDate}${childrenText} ${autoBadge}${bookmarkBadge}</span>
                    <span class="d-flex align-items-center">
                        <button class="btn btn-sm p-1 doubt-pin-btn" data-doubt-id="${doubt.doubt_id}" data-pinned="${doubt.pinned ? '1' : '0'}" title="${doubt.pinned ? 'Unpin' : 'Pin'}">
                            <i class="bi ${pinIcon}"></i>
                        </button>
                        <button class="doubt-delete-btn btn btn-sm p-1" data-doubt-id="${doubt.doubt_id}" title="Delete Doubt">
                            <i class="bi bi-trash"></i>
                        </button>
                    </span>
                </div>
                <div class="card-body doubt-preview-body" style="cursor:pointer;">
                    <p class="mb-2"><strong>Q:</strong> ${truncatedDoubt}</p>
                    <p class="mb-0 text-muted doubt-preview-answer" style="display:none;"><strong>A:</strong> ${truncatedAnswer}</p>
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
            // Don't trigger if clicking delete button or pin button
            if ($(e.target).closest('.doubt-delete-btn, .doubt-pin-btn').length > 0) {
                return;
            }
            
            const doubtId = $(this).data('doubt-id');
            self.openDoubtChat(doubtId);
        });
        
        // Toggle answer preview on body click
        $(document).off('click', '.doubt-preview-body').on('click', '.doubt-preview-body', function(e) {
            if ($(e.target).closest('.doubt-delete-btn, .doubt-pin-btn').length > 0) return;
            $(this).find('.doubt-preview-answer').slideToggle(150);
        });
        
        // Pin doubt button
        $(document).off('click', '.doubt-pin-btn').on('click', '.doubt-pin-btn', function(e) {
            e.stopPropagation();
            const btn = $(this);
            const doubtId = btn.data('doubt-id');
            const currentlyPinned = btn.data('pinned') === 1 || btn.data('pinned') === '1';
            const newPinned = !currentlyPinned;
            
            $.ajax({
                url: `/pin_doubt/${doubtId}`,
                method: 'POST',
                contentType: 'application/json',
                data: JSON.stringify({ pinned: newPinned }),
                success: function() {
                    // Refresh the overview
                    self.showDoubtsOverview(self.currentConversationId, self.currentMessageId);
                },
                error: function() {
                    if (typeof showToast === 'function') showToast('Failed to pin doubt', 'error');
                }
            });
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
    askNewDoubt: function(conversationId, messageId, selectedText = '', withContext = false) {
        this.currentConversationId = conversationId;
        this.currentMessageId = messageId;
        this.selectedText = selectedText;
        this.withContext = withContext;
        
        this.currentDoubtHistory = [];
        this.openDoubtChatModal();
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
                // Restore with_context from the root doubt so follow-up questions
                // use the same mode the thread was originally created with.
                self.withContext = !!data.doubt.with_context;

                // Get the full tree for this message and find the conversation thread
                const conversationId = data.doubt.conversation_id;
                const messageId = data.doubt.message_id;
                
                // If this is a non-root doubt, we need to find its root to filter the tree
                const targetDoubtId = data.doubt.doubt_id;
                
                return fetch(`/get_doubts/${conversationId}/${messageId}`)
                    .then(response => response.json())
                    .then(treeData => {
                        if (treeData.success && treeData.doubts) {
                            self._sectionStates = treeData.section_states || {};
                            // Find the root tree that contains our target doubt
                            function findInTree(node, id) {
                                if (node.doubt_id === id) return true;
                                return (node.children || []).some(c => findInTree(c, id));
                            }
                            const matchingRoot = treeData.doubts.find(root => findInTree(root, targetDoubtId));
                            treeData.doubts = matchingRoot ? [matchingRoot] : treeData.doubts.filter(d => d.doubt_id === targetDoubtId);
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
        
        // Initialize inline controls: populate preamble from settings, reset length to Medium
        this.initDoubtModalControls();
        
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
     * Initialize the inline doubt modal controls (length toggle + preamble dropdown)
     */
    initDoubtModalControls: function() {
        // Set length to medium
        $('.doubt-length-option').removeClass('active');
        $('.doubt-length-option[data-length="medium"]').addClass('active');
        $('#doubt-length-dropdown-btn').text('M');
        
        // Pre-select preamble options from settings
        const currentOpts = (window.chatSettingsState && window.chatSettingsState.doubt_preamble_options) || [];
        $('#doubt-preamble-dropdown-menu .doubt-preamble-option').each(function() {
            const val = $(this).data('value');
            if (currentOpts.includes(val)) {
                $(this).addClass('active');
            } else {
                $(this).removeClass('active');
            }
        });
        this._updatePreambleButtonLabel();
        
        // Preamble dropdown multi-select toggle
        $('#doubt-preamble-dropdown-menu .doubt-preamble-option').off('click').on('click', function(e) {
            e.preventDefault();
            e.stopPropagation();
            const val = $(this).data('value');
            if (val === '') {
                // "None" clears all
                $('#doubt-preamble-dropdown-menu .doubt-preamble-option').removeClass('active');
            } else {
                // Remove "None" selection when picking a real option
                $('#doubt-preamble-dropdown-menu .doubt-preamble-option[data-value=""]').removeClass('active');
                $(this).toggleClass('active');
            }
            DoubtManager._updatePreambleButtonLabel();
        });
        
        // Length dropdown click handler
        $('#doubt-length-dropdown-btn').parent().find('.doubt-length-option').off('click').on('click', function(e) {
            e.preventDefault();
            $('.doubt-length-option').removeClass('active');
            $(this).addClass('active');
            $('#doubt-length-dropdown-btn').text($(this).data('label'));
        });

        // Tools toggle
        $('#doubt-tools-toggle-btn').off('click').on('click', function() {
            $(this).toggleClass('active btn-outline-secondary btn-primary');
        });
    },
    
    _updatePreambleButtonLabel: function() {
        const selected = [];
        $('#doubt-preamble-dropdown-menu .doubt-preamble-option.active').each(function() {
            const val = $(this).data('value');
            if (val) selected.push(val);
        });
        const btn = $('#doubt-preamble-dropdown-btn');
        if (selected.length > 0) {
            btn.attr('title', 'Preamble: ' + selected.join(', '));
            btn.removeClass('btn-outline-secondary').addClass('btn-outline-primary');
        } else {
            btn.attr('title', 'Preamble');
            btn.removeClass('btn-outline-primary').addClass('btn-outline-secondary');
        }
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
            const assistantCard = this.createDoubtChatCard(doubt.doubt_answer, 'assistant', doubt.doubt_id, doubt.show_hide || 'show');
            // Set bookmark icon state if bookmarked
            if (doubt.bookmarked) {
                assistantCard.find('.doubt-bookmark-btn i').removeClass('bi-bookmark').addClass('bi-bookmark-fill');
            }
            messagesContainer.append(assistantCard);
        });
        
        // Scroll to bottom
        messagesContainer.scrollTop(messagesContainer[0].scrollHeight);
    },
    
    /**
     * Inject (idempotently) the [show]/[hide] collapse toggle into an assistant
     * doubt card header and apply the collapsed state. Mirrors the main-answer
     * show/hide. Safe to call repeatedly on the same card.
     *
     * @param {jQuery} card    - the .doubt-conversation-card element
     * @param {string} doubtId - the saved doubt_id (enables persistence)
     * @param {string} showHide - 'show' (expanded) or 'hide' (collapsed)
     */
    ensureDoubtAnswerToggle: function(card, doubtId, showHide) {
        if (!card || !card.length || !card.hasClass('assistant-doubt')) return;
        const $header = card.find('> .card-header').first();
        if (!$header.length) return;

        let $toggle = $header.find('.doubt-answer-collapse-toggle').first();
        if (!$toggle.length) {
            // Lay the header out as [ sender ............ actions ].
            $header.addClass('d-flex justify-content-between align-items-center');
            $toggle = $('<a href="#" class="doubt-answer-collapse-toggle" title="Collapse / expand this answer">[hide]</a>');
            // Prefer the right-hand actions group so it sits beside copy/Bottom.
            const $actions = $header.find('.doubt-card-actions').first();
            ($actions.length ? $actions : $header).append($toggle);
        }
        // Long answers also expose the Bottom button.
        $header.find('.scroll-to-bottom-btn').show();
        if (doubtId) {
            $toggle.attr('data-doubt-id', doubtId);
        }

        // Bottom mirror of the show/hide toggle — sits just left of the
        // scroll-to-top ("Top") button, mirroring the tabbed-answer bottom
        // toggle. Shares the .doubt-answer-collapse-toggle class so the existing
        // delegated click handler drives it.
        let $bottomToggle = card.find('> .doubt-answer-collapse-toggle-bottom').first();
        if (!$bottomToggle.length) {
            $bottomToggle = $('<a href="#" class="doubt-answer-collapse-toggle doubt-answer-collapse-toggle-bottom" title="Collapse / expand this answer">[hide]</a>');
            card.append($bottomToggle);
        }
        if (doubtId) {
            $bottomToggle.attr('data-doubt-id', doubtId);
        }

        const collapsed = (showHide === 'hide');
        card.toggleClass('doubt-answer-collapsed', collapsed);
        $toggle.text(collapsed ? '[show]' : '[hide]');
        $bottomToggle.text(collapsed ? '[show]' : '[hide]');

        // Position the bottom toggle after the Top button has been laid out
        // (it is added with a short delay), and again on the next frame.
        const self = this;
        setTimeout(function() { self.positionDoubtBottomToggle(card); }, 60);
        if (typeof requestAnimationFrame === 'function') {
            requestAnimationFrame(function() { self.positionDoubtBottomToggle(card); });
        }
    },

    /**
     * Position the bottom show/hide toggle just to the LEFT of the card's
     * scroll-to-top button, mirroring positionTabsBottomToggle() for tabs.
     *
     * @param {jQuery} card - the .doubt-conversation-card element
     */
    positionDoubtBottomToggle: function(card) {
        if (!card || !card.length) return;
        const $btn = card.find('> .doubt-answer-collapse-toggle-bottom').first();
        if (!$btn.length) return;
        const $scrollBtn = card.find('> .scroll-to-top-btn').first();
        let rightOffset = 70; // fallback before the Top button measures
        if ($scrollBtn.length) {
            // 5px = Top button's own right offset; +10px gap between the two.
            rightOffset = 5 + ($scrollBtn.outerWidth(true) || 60) + 10;
        }
        $btn.css('right', rightOffset + 'px');
    },

    /**
     * Create a chat card for doubt conversation
     */
    createDoubtChatCard: function(text, sender, doubtId, showHide) {
        text = text || '';
        const isUser = sender === 'user';
        const senderClass = isUser ? 'user-doubt' : 'assistant-doubt';
        const senderText = isUser ? 'You' : 'Assistant';
        
        // Always create delete button for user messages, even if doubtId is null initially
        const deleteBtn = isUser ? `<button class="doubt-delete-btn float-right" data-doubt-id="${doubtId || ''}" title="Delete Doubt"><i class="bi bi-trash"></i></button>` : '';
        
        // Bookmark button for assistant cards (only if doubtId exists - i.e. saved doubts)
        const bookmarkBtn = (!isUser && doubtId) ? `<button class="btn btn-sm p-1 doubt-bookmark-btn" data-doubt-id="${doubtId}" title="Bookmark"><i class="bi bi-bookmark"></i></button>` : '';
        
        // Regenerate button for assistant cards
        const regenBtn = (!isUser && doubtId) ? `<button class="btn btn-sm p-1 doubt-regen-btn" data-doubt-id="${doubtId}" title="Regenerate answer"><i class="bi bi-arrow-clockwise"></i></button>` : '';
        
        // Render content based on sender type
        let renderedContent;
        if (isUser) {
            // User messages are plain text - just convert line breaks
            renderedContent = text.replace(/\n/g, '<br>');
        } else {
            // Check for progressive disclosure markers
            const hasSections = text && text.includes('<tldr>') && text.includes('<explanation>') && text.includes('<deep_dive>');
            if (hasSections) {
                const tldr = (text.match(/<tldr>([\s\S]*?)<\/tldr>/) || [])[1] || '';
                const explanation = (text.match(/<explanation>([\s\S]*?)<\/explanation>/) || [])[1] || '';
                const deepDive = (text.match(/<deep_dive>([\s\S]*?)<\/deep_dive>/) || [])[1] || '';
                const renderMd = (t) => (typeof marked !== 'undefined' && marked.parse) ? marked.parse(t.trim()) : t.replace(/\n/g, '<br>');
                const explainHash = `doubt_${doubtId}_explain`;
                const deepHash = `doubt_${doubtId}_deep`;
                // Check saved section states
                const sectionStates = this._sectionStates || {};
                const explainHidden = sectionStates[explainHash];
                const deepHidden = sectionStates[deepHash] !== false; // default hidden
                renderedContent = `
                    <div class="doubt-progressive-disclosure">
                        <div class="doubt-section-tldr"><strong>TL;DR</strong> — ${renderMd(tldr)}</div>
                        <details class="section-details doubt-section-explain" data-section-hash="${explainHash}" ${explainHidden === true ? '' : 'open'}>
                            <summary><strong>Explanation</strong></summary>
                            <div class="doubt-section-content">${renderMd(explanation)}</div>
                        </details>
                        <details class="section-details doubt-section-deep" data-section-hash="${deepHash}" ${deepHidden ? '' : 'open'}>
                            <summary><strong>Deep Dive</strong></summary>
                            <div class="doubt-section-content">${renderMd(deepDive)}</div>
                        </details>
                    </div>`;
            } else {
                // Assistant messages should be rendered as markdown
                if (typeof marked !== 'undefined' && marked.parse) {
                    renderedContent = marked.parse(text);
                } else {
                    // Fallback if marked is not available
                    renderedContent = text.replace(/\n/g, '<br>');
                }
            }
        }
        
        const card = $(`
            <div class="card doubt-conversation-card ${senderClass}" data-doubt-id="${doubtId || ''}" style="position: relative;">
                <div class="card-header d-flex justify-content-between align-items-center">
                    <span class="doubt-card-sender">${senderText}</span>
                    <span class="doubt-card-actions d-flex align-items-center">
                        <button class="btn btn-sm p-1 scroll-to-bottom-btn doubt-scroll-bottom" title="Jump to the bottom of this message" style="display:none;">Bottom <i class="bi bi-arrow-down-short"></i></button>
                        ${regenBtn}
                        ${bookmarkBtn}
                        <button class="doubt-copy-btn btn btn-sm p-1" title="Copy text"><i class="bi bi-clipboard"></i></button>
                        ${deleteBtn}
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
        
        // Trigger MathJax typesetting for assistant cards
        if (!isUser) {
            setTimeout(function() {
                if (typeof MathJax !== 'undefined' && MathJax.Hub) {
                    MathJax.Hub.Queue(["Typeset", MathJax.Hub, card.find('.card-body')[0]]);
                }
            }, 50);
        }
        
        // Add Top/Bottom nav controls for messages that are long enough — on BOTH
        // user question cards and assistant answer cards.
        if (text && text.length > 300) {
            card.find('.scroll-to-bottom-btn').show();
            // Use setTimeout to ensure card is in DOM before adding button
            setTimeout(function() {
                if (typeof window.addScrollToTopButton === 'function') {
                    window.addScrollToTopButton(card, '↑ Top', 'doubt-scroll-top');
                }
            }, 50);
        }

        // Add the collapse (show/hide) toggle for long assistant answers, mirroring
        // the main-answer show/hide. Restores the persisted state (default expanded).
        // Skip when progressive disclosure sections handle their own collapse.
        const hasDisclosure = text.includes('<tldr>') && text.includes('<explanation>') && text.includes('<deep_dive>');
        if (!isUser && text && text.length > 300 && !hasDisclosure) {
            this.ensureDoubtAnswerToggle(card, doubtId, showHide || 'show');
        }

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
        
        // Initialize gamification system if available (for rewards/penalties)
        if (typeof initializeGamificationSystem !== 'undefined') {
            initializeGamificationSystem();
        }
    },
    
    /**
     * Set up event handlers for chat modal
     */
    setupChatEventHandlers: function() {
        const self = this;
        const input = $('#doubt-chat-input');
        const sendBtn = $('#doubt-chat-send-btn');

        // Section toggle persistence for progressive disclosure
        $('#doubt-chat-messages').off('click.doubtSection').on('click.doubtSection', '.section-details > summary', function() {
            const $section = $(this).closest('.section-details');
            const sectionHash = $section.attr('data-section-hash');
            if (!sectionHash) return;
            setTimeout(function() {
                const isHidden = !$section.prop('open');
                self._sectionStates = self._sectionStates || {};
                self._sectionStates[sectionHash] = isHidden;
                if (self.currentConversationId && typeof persistSectionState === 'function') {
                    persistSectionState(self.currentConversationId, sectionHash, isHidden);
                }
            }, 0);
        });

        // Back button — close chat and reopen overview
        $('#doubt-chat-back-btn').off('click').on('click', function() {
            $('#doubt-chat-modal').modal('hide');
            DoubtManager.showDoubtsOverview(self.currentConversationId, self.currentMessageId);
        });
        
        // Copy Thread button — copies entire thread as markdown
        $('#doubt-copy-thread-btn').off('click').on('click', function() {
            if (!self.currentDoubtHistory || self.currentDoubtHistory.length === 0) {
                if (typeof showToast === 'function') showToast('No thread to copy', 'warning');
                return;
            }
            const threadText = self.currentDoubtHistory.map(d =>
                `## Q: ${d.doubt_text}\n\n${d.doubt_answer}\n\n---`
            ).join('\n\n');
            navigator.clipboard.writeText(threadText).then(() => {
                if (typeof showToast === 'function') showToast('Thread copied to clipboard', 'success');
            }).catch(() => {
                if (typeof showToast === 'function') showToast('Failed to copy', 'error');
            });
        });
        
        // Summarize Thread button — calls summarize endpoint and streams into a new card
        $('#doubt-summarize-thread-btn').off('click').on('click', function() {
            if (!self.currentDoubtHistory || self.currentDoubtHistory.length === 0) {
                if (typeof showToast === 'function') showToast('No thread to summarize', 'warning');
                return;
            }
            const btn = $(this);
            btn.prop('disabled', true);
            
            // Use the last doubt in history as the anchor
            const lastDoubt = self.currentDoubtHistory[self.currentDoubtHistory.length - 1];
            const doubtId = lastDoubt.doubt_id;
            
            // Append user card + empty assistant card
            const messagesContainer = $('#doubt-chat-messages');
            const userCard = self.createDoubtChatCard('Thread Summary', 'user', null);
            messagesContainer.append(userCard);
            const assistantCard = self.createDoubtChatCard('', 'assistant', null);
            messagesContainer.append(assistantCard);
            const cardBody = assistantCard.find('.card-body');
            cardBody.html('<div class="text-center"><i class="bi bi-arrow-clockwise spin-animation"></i> Summarizing...</div>');
            messagesContainer.scrollTop(messagesContainer[0].scrollHeight);
            
            fetch(`/summarize_doubt_thread/${doubtId}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({})
            }).then(response => {
                const reader = response.body.getReader();
                const decoder = new TextDecoder();
                let accumulated = '';
                cardBody.empty();
                
                function readChunk() {
                    reader.read().then(({ done, value }) => {
                        if (done) {
                            btn.prop('disabled', false);
                            if (typeof MathJax !== 'undefined' && MathJax.Hub) {
                                MathJax.Hub.Queue(["Typeset", MathJax.Hub, cardBody[0]]);
                            }
                            return;
                        }
                        const text = decoder.decode(value, { stream: true });
                        const lines = text.split('\n').filter(l => l.trim());
                        for (const line of lines) {
                            try {
                                const data = JSON.parse(line);
                                if (data.text) {
                                    accumulated += data.text;
                                    const rendered = (typeof marked !== 'undefined' && marked.parse) ? marked.parse(accumulated) : accumulated.replace(/\n/g, '<br>');
                                    cardBody.html(rendered);
                                    messagesContainer.scrollTop(messagesContainer[0].scrollHeight);
                                }
                                if (data.completed && data.doubt_id) {
                                    // Update card data attributes
                                    assistantCard.attr('data-doubt-id', data.doubt_id);
                                    userCard.attr('data-doubt-id', data.doubt_id);
                                    // Add to history
                                    self.currentDoubtHistory.push({
                                        doubt_id: data.doubt_id,
                                        doubt_text: 'Thread Summary',
                                        doubt_answer: accumulated,
                                        parent_doubt_id: doubtId,
                                        is_root_doubt: false,
                                        bookmarked: false,
                                        pinned: false,
                                        show_hide: 'show',
                                    });
                                }
                            } catch(e) {}
                        }
                        readChunk();
                    });
                }
                readChunk();
            }).catch(err => {
                btn.prop('disabled', false);
                cardBody.html('<p class="text-danger">Summarization failed</p>');
            });
        });
        
        // Continue as Conversation button — creates new conversation from doubt thread
        $('#doubt-to-conversation-btn').off('click').on('click', function() {
            if (!self.currentDoubtHistory || self.currentDoubtHistory.length === 0) {
                if (typeof showToast === 'function') showToast('No thread to continue', 'warning');
                return;
            }
            const btn = $(this);
            btn.prop('disabled', true);
            const doubtId = self.currentDoubtHistory[0].doubt_id;
            
            $.ajax({
                url: `/create_conversation_from_doubt_thread/${doubtId}`,
                method: 'POST',
                contentType: 'application/json',
                data: JSON.stringify({}),
                success: function(data) {
                    btn.prop('disabled', false);
                    if (data.success && data.conversation_id) {
                        $('#doubt-chat-modal').modal('hide');
                        // Navigate to the new conversation
                        if (typeof ConversationManager !== 'undefined' && ConversationManager.loadConversation) {
                            ConversationManager.loadConversation(data.conversation_id);
                        }
                        if (typeof showToast === 'function') showToast('New conversation created from doubt thread', 'success');
                    }
                },
                error: function() {
                    btn.prop('disabled', false);
                    if (typeof showToast === 'function') showToast('Failed to create conversation', 'error');
                }
            });
        });
        
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

        // Copy a doubt card's text (works for both the user question and the
        // assistant answer cards).
        $(document).off('click', '#doubt-chat-messages .doubt-copy-btn').on('click', '#doubt-chat-messages .doubt-copy-btn', function(e) {
            e.preventDefault();
            e.stopPropagation();
            self.copyDoubtCardText($(this).closest('.doubt-conversation-card'));
        });

        // Collapse / expand an assistant doubt answer (persisted per doubt).
        $(document).off('click', '#doubt-chat-messages .doubt-answer-collapse-toggle').on('click', '#doubt-chat-messages .doubt-answer-collapse-toggle', function(e) {
            e.preventDefault();
            e.stopPropagation();
            const $toggle = $(this);
            const $card = $toggle.closest('.doubt-conversation-card');
            const nowCollapsed = !$card.hasClass('doubt-answer-collapsed');
            $card.toggleClass('doubt-answer-collapsed', nowCollapsed);
            // Sync every toggle on this card (header + bottom mirror).
            $card.find('.doubt-answer-collapse-toggle').text(nowCollapsed ? '[show]' : '[hide]');

            // Persist (best-effort) — only once the doubt has a saved id.
            const doubtId = $toggle.attr('data-doubt-id');
            if (doubtId) {
                fetch('/show_hide_doubt/' + encodeURIComponent(doubtId), {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ show_hide: nowCollapsed ? 'hide' : 'show' })
                }).then(function(r) {
                    if (!r.ok) console.error('Failed to persist doubt show/hide:', r.status);
                }).catch(function(err) {
                    console.error('Failed to persist doubt show/hide:', err);
                });
            }
        });

        // Bookmark a doubt answer
        $(document).off('click', '#doubt-chat-messages .doubt-bookmark-btn').on('click', '#doubt-chat-messages .doubt-bookmark-btn', function(e) {
            e.preventDefault();
            e.stopPropagation();
            const btn = $(this);
            const doubtId = btn.data('doubt-id');
            const icon = btn.find('i');
            const currentlyBookmarked = icon.hasClass('bi-bookmark-fill');
            const newBookmarked = !currentlyBookmarked;
            
            $.ajax({
                url: `/bookmark_doubt/${doubtId}`,
                method: 'POST',
                contentType: 'application/json',
                data: JSON.stringify({ bookmarked: newBookmarked }),
                success: function() {
                    icon.toggleClass('bi-bookmark bi-bookmark-fill');
                },
                error: function() {
                    if (typeof showToast === 'function') showToast('Failed to bookmark', 'error');
                }
            });
        });

        // Regenerate a doubt answer
        $(document).off('click', '#doubt-chat-messages .doubt-regen-btn').on('click', '#doubt-chat-messages .doubt-regen-btn', function(e) {
            e.preventDefault();
            e.stopPropagation();
            const btn = $(this);
            const doubtId = btn.data('doubt-id');
            const card = btn.closest('.doubt-conversation-card');
            const cardBody = card.find('.card-body');
            
            // Check if it has children (warn user)
            const hasChildren = self.currentDoubtHistory.some(d => d.parent_doubt_id === doubtId);
            if (hasChildren) {
                showToast('Note: Follow-up questions were based on the previous answer', 'warning');
            }
            
            // Show spinner, disable button
            btn.prop('disabled', true);
            cardBody.html('<div class="text-center"><i class="bi bi-arrow-clockwise spin-animation"></i> Regenerating...</div>');
            
            // Get current preamble options from inline controls or settings
            const preambleOpts = self.getActiveDoubtPreambleOptions();
            
            // Stream regeneration
            fetch(`/regenerate_doubt/${doubtId}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ preamble_options: preambleOpts })
            }).then(response => {
                const reader = response.body.getReader();
                const decoder = new TextDecoder();
                let accumulated = '';
                cardBody.empty();
                
                function readChunk() {
                    reader.read().then(({ done, value }) => {
                        if (done) {
                            btn.prop('disabled', false);
                            // Update in-memory history
                            const histEntry = self.currentDoubtHistory.find(d => d.doubt_id === doubtId);
                            if (histEntry) histEntry.doubt_answer = accumulated;
                            // Re-render math
                            if (typeof MathJax !== 'undefined' && MathJax.Hub) {
                                MathJax.Hub.Queue(["Typeset", MathJax.Hub, cardBody[0]]);
                            }
                            return;
                        }
                        const text = decoder.decode(value, { stream: true });
                        const lines = text.split('\n').filter(l => l.trim());
                        for (const line of lines) {
                            try {
                                const data = JSON.parse(line);
                                if (data.text) {
                                    accumulated += data.text;
                                    const rendered = (typeof marked !== 'undefined' && marked.parse) ? marked.parse(accumulated) : accumulated.replace(/\n/g, '<br>');
                                    cardBody.html(rendered);
                                }
                            } catch(e) {}
                        }
                        readChunk();
                    });
                }
                readChunk();
            }).catch(err => {
                btn.prop('disabled', false);
                cardBody.html('<p class="text-danger">Regeneration failed</p>');
                if (typeof showToast === 'function') showToast('Regeneration failed', 'error');
            });
        });
    },
    
    /**
     * Get active doubt preamble options from inline modal controls or settings fallback
     */
    getActiveDoubtPreambleOptions: function() {
        // Read from dropdown menu active items, fallback to settings
        let opts = [];
        const activeItems = $('#doubt-preamble-dropdown-menu .doubt-preamble-option.active');
        if (activeItems.length > 0) {
            activeItems.each(function() {
                const val = $(this).data('value');
                if (val) opts.push(val);
            });
        } else {
            opts = [...((window.chatSettingsState && window.chatSettingsState.doubt_preamble_options) || [])];
        }
        
        // Merge length toggle: Short/Long added to preamble list, Medium = neither
        const activeLength = $('.doubt-length-option.active').data('length');
        opts = opts.filter(o => o !== 'Short' && o !== 'Long');
        if (activeLength === 'short') opts.push('Short');
        else if (activeLength === 'long') opts.push('Long');
        
        return opts;
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
        
        // Create assistant card for streaming response with unique ID for tracking
        const assistantCard = this.createDoubtChatCard('', 'assistant', null);
        const cardId = 'doubt-card-' + Date.now(); // Unique ID for this card
        assistantCard.attr('data-card-id', cardId);
        $('#doubt-chat-messages').append(assistantCard);
        
        // Clear input
        input.val('');
        
        // Intentionally do NOT scroll to the bottom here. New cards are appended
        // below the current view, so leaving the scroll position alone lets the
        // user keep reading whatever they were reading while the answer streams
        // in below.
        
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
        
        // Get reward level from main chat selector (since doubt-specific selector was removed)
        const rewardLevel = $('#rewardLevelSelector').length > 0 ? parseInt($('#rewardLevelSelector').val()) || 0 : 0;
        
        const requestBody = {
            doubt_text: doubtText,
            reward_level: rewardLevel,
            selected_text: this.selectedText || '',
            with_context: this.withContext || false,
            preamble_options: this.getActiveDoubtPreambleOptions(),
            tools_enabled: $('#doubt-tools-toggle-btn').hasClass('active'),
            length: ($('.doubt-length-option.active').data('length') || 'medium')
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
        
        // DEBUG: Log initial state
        console.log('=== DOUBT STREAMING DEBUG START ===');
        console.log('AssistantCard exists:', assistantCard && assistantCard.length > 0);
        console.log('AssistantCard ID:', assistantCard.attr('data-card-id'));
        console.log('AssistantCard HTML:', assistantCard.prop('outerHTML')?.substring(0, 200));
        
        // Store the card ID immediately for later use
        const storedCardId = assistantCard.attr('data-card-id');
        console.log('Stored card ID for later:', storedCardId);
        
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
                    console.log('=== DONE BRANCH TRIGGERED ===');
                    console.log('Done flag:', done);
                    console.log('isCancelled:', isCancelled);
                    console.log('This branch may be dead code if streaming completes via part.completed');
                    
                    // Reset UI state - hide stop button and clear controller
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
                                userCard.attr('data-doubt-id', doubtId);
                            }
                            if (typeof assistantCard !== 'undefined' && assistantCard && assistantCard.length > 0) {
                                assistantCard.attr('data-doubt-id', doubtId);
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
                    
                    // Normal completion - update cards and history
                    if (doubtId) {
                        // Update assistant card (if it has a delete button)
                        assistantCard.find('.doubt-delete-btn').data('doubt-id', doubtId);
                        assistantCard.attr('data-doubt-id', doubtId);
                        
                        // Update user card with doubt ID - this is the main fix
                        if (userCard && userCard.length > 0) {
                            const userDeleteBtn = userCard.find('.doubt-delete-btn');
                            userDeleteBtn.data('doubt-id', doubtId);
                            // Re-enable the delete button and remove muted styling
                            userDeleteBtn.prop('disabled', false).removeClass('text-muted');
                            userCard.attr('data-doubt-id', doubtId);
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
                    
                    // Reveal doubts indicator for this message
                    $('.has-doubts-btn[message-id="' + self.currentMessageId + '"]').show();
                    // Trigger MathJax typesetting on completed response
                    if (typeof MathJax !== 'undefined' && MathJax.Hub) {
                        MathJax.Hub.Queue(["Typeset", MathJax.Hub, assistantBody[0]]);
                    }
                    
                    // Inject the collapse (show/hide) toggle on the freshly-streamed
                    // answer (expanded). data-doubt-id is set so the toggle persists.
                    if (accumulatedText.length > 300) {
                        setTimeout(function() {
                            let toggleCard = storedCardId ? $('[data-card-id="' + storedCardId + '"]') : null;
                            if (!toggleCard || !toggleCard.length) toggleCard = assistantCard;
                            if (toggleCard && toggleCard.length) {
                                self.ensureDoubtAnswerToggle(toggleCard, doubtId, 'show');
                            }
                        }, 60);
                    }

                    // Add scroll-to-top button for streamed doubt response if long enough
                    console.log('=== DOUBT BUTTON ADDITION DEBUG ===');
                    console.log('Text length:', accumulatedText.length);
                    console.log('Threshold: 300 characters');
                    console.log('Should add button:', accumulatedText.length > 300);
                    
                    if (accumulatedText.length > 300) {
                        // Small delay to ensure DOM is stable after streaming completes
                        setTimeout(function() {
                            console.log('--- Attempting to add button after delay ---');
                            console.log('Stored card ID:', storedCardId);
                            
                            // Method 1: Try to find by stored ID
                            let currentCard = null;
                            if (storedCardId) {
                                currentCard = $(`[data-card-id="${storedCardId}"]`);
                                console.log('Method 1 - Find by stored ID:', storedCardId);
                                console.log('Card found by ID:', currentCard.length > 0);
                                if (currentCard.length > 0) {
                                    console.log('Card classes:', currentCard.attr('class'));
                                    console.log('Card position style:', currentCard.css('position'));
                                }
                            }
                            
                            // Method 2: Try original assistantCard reference
                            if ((!currentCard || currentCard.length === 0) && assistantCard && assistantCard.length > 0) {
                                currentCard = assistantCard;
                                console.log('Method 2 - Using original assistantCard reference');
                                console.log('Card exists:', currentCard.length > 0);
                            }
                            
                            // Method 3: Fallback to finding the last assistant card
                            if (!currentCard || currentCard.length === 0) {
                                currentCard = $('#doubt-chat-messages .doubt-conversation-card.assistant-doubt').last();
                                console.log('Method 3 - Using fallback (last assistant card)');
                                console.log('Card found:', currentCard.length > 0);
                                console.log('Total assistant cards in modal:', $('#doubt-chat-messages .doubt-conversation-card.assistant-doubt').length);
                            }
                            
                            if (currentCard && currentCard.length > 0) {
                                console.log('--- Card found, checking for existing button ---');
                                const existingButtons = currentCard.find('.scroll-to-top-btn');
                                console.log('Existing buttons:', existingButtons.length);
                                
                                if (existingButtons.length === 0) {
                                    console.log('--- No existing button, checking addScrollToTopButton function ---');
                                    console.log('window.addScrollToTopButton type:', typeof window.addScrollToTopButton);
                                    console.log('window.addScrollToTopButton exists:', typeof window.addScrollToTopButton === 'function');
                                    
                                    if (typeof window.addScrollToTopButton === 'function') {
                                        console.log('--- Calling addScrollToTopButton ---');
                                        console.log('Card HTML before:', currentCard.prop('outerHTML')?.substring(0, 200));
                                        
                                        // Call the function
                                        const result = window.addScrollToTopButton(currentCard, '↑ Top', 'doubt-scroll-top');
                                        console.log('Function returned:', result);
                                        
                                        // Immediate verification
                                        const immediateCheck = currentCard.find('.scroll-to-top-btn').length;
                                        console.log('Immediate button count:', immediateCheck);
                                        
                                        // Delayed verification
                                        setTimeout(function() {
                                            const delayedCheck = currentCard.find('.scroll-to-top-btn').length;
                                            console.log('--- Final verification ---');
                                            console.log('Button count after delay:', delayedCheck);
                                            console.log('Card HTML after:', currentCard.prop('outerHTML')?.substring(0, 300));
                                            
                                            if (delayedCheck > 0) {
                                                console.log('✅ SUCCESS: Button added to streamed doubt');
                                                const btn = currentCard.find('.scroll-to-top-btn').first();
                                                console.log('Button position:', btn.css('position'));
                                                console.log('Button bottom:', btn.css('bottom'));
                                                console.log('Button right:', btn.css('right'));
                                            } else {
                                                console.error('❌ FAILED: Button was not added');
                                                console.log('Card still exists in DOM:', $(currentCard).length > 0);
                                                console.log('Card parent exists:', currentCard.parent().length > 0);
                                            }
                                            console.log('=== DOUBT BUTTON DEBUG END ===');
                                        }, 100);
                                    } else {
                                        console.error('❌ addScrollToTopButton function not available');
                                    }
                                } else {
                                    console.log('⚠️ Button already exists on card');
                                }
                            } else {
                                console.error('❌ Could not find assistant card for button addition');
                                console.log('All cards in modal:', $('#doubt-chat-messages .doubt-conversation-card').length);
                            }
                        }, 500); // Increased delay to ensure modal is fully rendered
                    } else {
                        console.log('ℹ️ Text too short for button:', accumulatedText.length, 'characters');
                    }
                    
                    // Scroll to bottom
                    // const messagesContainer = $('#doubt-chat-messages');
                    // messagesContainer.scrollTop(messagesContainer[0].scrollHeight);
                    
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
                        // Parse and handle gamification tags before processing (reuse from common-chat.js)
                        let processedText = part.text;
                        if (typeof parseGamificationTags !== 'undefined') {
                            processedText = parseGamificationTags(part.text, assistantCard);
                        }
                        
                        // Check for doubt_id tags
                        const doubtIdMatch = processedText.match(/<doubt_id>([^<]+)<\/doubt_id>/);
                        if (doubtIdMatch) {
                            doubtId = doubtIdMatch[1];
                            // Remove the tags from display
                            processedText = processedText.replace(/<doubt_id>[^<]+<\/doubt_id>/, '');
                        }
                        
                        accumulatedText += processedText;
                        // Render markdown if available — strip progressive disclosure markers during streaming
                        const displayText = accumulatedText.replace(/<\/?(?:tldr|explanation|deep_dive)>/g, '');
                        if (typeof marked !== 'undefined' && marked.parse) {
                            assistantBody.html(marked.parse(displayText));
                        } else {
                            assistantBody.html(displayText.replace(/\n/g, '<br>'));
                        }
                        if (typeof renderMermaidIn === 'function') renderMermaidIn(assistantBody);
                    }
                    
                    if (part.completed) {
                        // Final processing
                        if (part.doubt_id) {
                            doubtId = part.doubt_id;
                        }
                        
                        // Update doubt history
                        if (doubtId) {
                            // Update user card with doubt ID
                            if (userCard && userCard.length > 0) {
                                const userDeleteBtn = userCard.find('.doubt-delete-btn');
                                userDeleteBtn.data('doubt-id', doubtId);
                                userDeleteBtn.prop('disabled', false).removeClass('text-muted');
                                userCard.attr('data-doubt-id', doubtId);
                            }
                            if (typeof assistantCard !== 'undefined' && assistantCard && assistantCard.length > 0) {
                                assistantCard.attr('data-doubt-id', doubtId);
                            }
                            
                            // Update the current doubt history
                            if (self.currentDoubtHistory) {
                                self.currentDoubtHistory.push({
                                    doubt_id: doubtId,
                                    doubt_text: userCard ? userCard.find('.card-body').text() : '',
                                    doubt_answer: accumulatedText
                                });
                            }
                        }
                        
                        // Ensure stop button is hidden on completion
                        $('#stop-doubt-chat-button').hide();
                        currentDoubtStreamingController = null;
                        // Reveal doubts indicator for this message
                        $('.has-doubts-btn[message-id="' + self.currentMessageId + '"]').show();
                        // Trigger MathJax typesetting on completed response
                        if (typeof MathJax !== 'undefined' && MathJax.Hub) {
                            MathJax.Hub.Queue(["Typeset", MathJax.Hub, assistantBody[0]]);
                        }
                        
                        // Re-render with progressive disclosure sections if markers present
                        if (accumulatedText.includes('<tldr>') && accumulatedText.includes('<explanation>') && accumulatedText.includes('<deep_dive>')) {
                            const tldr = (accumulatedText.match(/<tldr>([\s\S]*?)<\/tldr>/) || [])[1] || '';
                            const explanation = (accumulatedText.match(/<explanation>([\s\S]*?)<\/explanation>/) || [])[1] || '';
                            const deepDive = (accumulatedText.match(/<deep_dive>([\s\S]*?)<\/deep_dive>/) || [])[1] || '';
                            const renderMd = (t) => (typeof marked !== 'undefined' && marked.parse) ? marked.parse(t.trim()) : t.replace(/\n/g, '<br>');
                            const explainHash = `doubt_${doubtId}_explain`;
                            const deepHash = `doubt_${doubtId}_deep`;
                            assistantBody.html(`
                                <div class="doubt-progressive-disclosure">
                                    <div class="doubt-section-tldr"><strong>TL;DR</strong> — ${renderMd(tldr)}</div>
                                    <details class="section-details doubt-section-explain" data-section-hash="${explainHash}" open>
                                        <summary><strong>Explanation</strong></summary>
                                        <div class="doubt-section-content">${renderMd(explanation)}</div>
                                    </details>
                                    <details class="section-details doubt-section-deep" data-section-hash="${deepHash}">
                                        <summary><strong>Deep Dive</strong></summary>
                                        <div class="doubt-section-content">${renderMd(deepDive)}</div>
                                    </details>
                                </div>`);
                            if (typeof MathJax !== 'undefined' && MathJax.Hub) {
                                MathJax.Hub.Queue(["Typeset", MathJax.Hub, assistantBody[0]]);
                            }
                        }

                        // Inject the collapse (show/hide) toggle on the freshly-streamed
                        // answer (expanded). data-doubt-id is set so the toggle persists.
                        // Skip if progressive disclosure sections are present (they handle their own collapse).
                        const hasProgressiveSections = accumulatedText.includes('<tldr>') && accumulatedText.includes('<explanation>') && accumulatedText.includes('<deep_dive>');
                        if (accumulatedText.length > 300 && !hasProgressiveSections) {
                            setTimeout(function() {
                                let toggleCard = storedCardId ? $('[data-card-id="' + storedCardId + '"]') : null;
                                if (!toggleCard || !toggleCard.length) toggleCard = assistantCard;
                                if (toggleCard && toggleCard.length) {
                                    self.ensureDoubtAnswerToggle(toggleCard, doubtId, 'show');
                                }
                            }, 60);
                        }

                        // Add scroll-to-top button when streaming completes via completed flag
                        console.log('=== DOUBT BUTTON ADDITION DEBUG (via completed flag) ===');
                        console.log('Text length:', accumulatedText.length);
                        console.log('Threshold: 300 characters');
                        console.log('Should add button:', accumulatedText.length > 300);
                        
                        if (accumulatedText.length > 300) {
                            setTimeout(function() {
                                console.log('--- Adding button after completed flag ---');
                                console.log('Stored card ID:', storedCardId);
                                
                                // Find the card
                                let currentCard = null;
                                if (storedCardId) {
                                    currentCard = $(`[data-card-id="${storedCardId}"]`);
                                    console.log('Found card by ID:', currentCard.length > 0);
                                }
                                
                                if (!currentCard || currentCard.length === 0) {
                                    currentCard = $('#doubt-chat-messages .doubt-conversation-card.assistant-doubt').last();
                                    console.log('Using fallback - last assistant card');
                                }
                                
                                if (currentCard && currentCard.length > 0) {
                                    if (currentCard.find('.scroll-to-top-btn').length === 0) {
                                        if (typeof window.addScrollToTopButton === 'function') {
                                            console.log('Calling addScrollToTopButton...');
                                            window.addScrollToTopButton(currentCard, '↑ Top', 'doubt-scroll-top');
                                            
                                            // Verify
                                            setTimeout(function() {
                                                const buttonCount = currentCard.find('.scroll-to-top-btn').length;
                                                if (buttonCount > 0) {
                                                    console.log('✅ Button successfully added via completed flag');
                                                } else {
                                                    console.error('❌ Button was not added');
                                                }
                                            }, 100);
                                        }
                                    }
                                } else {
                                    console.error('Could not find card for button');
                                }
                            }, 500);
                        }
                        
                        // Scroll to bottom after completion
                        // const messagesContainer = $('#doubt-chat-messages');
                        // messagesContainer.scrollTop(messagesContainer[0].scrollHeight);
                        
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
                    // Don't replace content on cancellation - the cancellation logic above handles it
                    console.log('Doubt stream was cancelled by user');
                } else {
                    assistantBody.html(`<div class="alert alert-danger alert-sm">Streaming error: ${error.message}</div>`);
                }
            }
        }
        
        read();
    },
    
    /**
     * Copy a doubt card's text to the clipboard. Prefers the stashed raw text
     * (original markdown / question) and falls back to the rendered body text.
     *
     * @param {jQuery} $card - the .doubt-conversation-card
     */
    copyDoubtCardText: function($card) {
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
            } catch (e) {
                bad();
            }
        }
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
        
        if (!confirm('Are you sure you want to delete this doubt? This will also delete all of its follow-up doubts (its entire sub-tree). This action cannot be undone.')) {
            return;
        }
        
        const self = this;
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
                    self.showDoubtsOverview(self.currentConversationId, self.currentMessageId);
                }
                
                if ($('#doubt-chat-modal').hasClass('show')) {
                    // The backend deletes the whole sub-tree, so remove every card
                    // (question + answer) belonging to the deleted doubt ids.
                    const deletedIds = (data.deleted_doubt_ids && data.deleted_doubt_ids.length)
                        ? data.deleted_doubt_ids
                        : [doubtId];
                    deletedIds.forEach(function(id) {
                        $(`#doubt-chat-messages .doubt-conversation-card[data-doubt-id="${id}"]`)
                            .fadeOut(300, function() {
                                $(this).remove();
                            });
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
    },
    
    // ========================
    // Global Doubts Modal
    // ========================
    
    globalDoubtsPage: 1,
    globalDoubtsFilter: 'all',
    globalDoubtsSearch: '',
    
    openGlobalDoubtsModal: function() {
        this.globalDoubtsPage = 1;
        this.globalDoubtsFilter = 'all';
        this.globalDoubtsSearch = '';
        $('#global-doubts-search').val('');
        $('.global-doubts-filter').removeClass('active');
        $('.global-doubts-filter[data-filter="all"]').addClass('active');
        this.loadGlobalDoubts();
        $('#global-doubts-modal').modal('show');
    },
    
    loadGlobalDoubts: function() {
        const self = this;
        const params = new URLSearchParams({
            page: this.globalDoubtsPage,
            page_size: 20,
            search: this.globalDoubtsSearch,
            filter: this.globalDoubtsFilter,
        });
        $.get(`/get_all_doubts?${params.toString()}`, function(data) {
            if (data.success) {
                self.renderGlobalDoubtsList(data.doubts, data.total, data.page, data.page_size);
            }
        });
    },
    
    renderGlobalDoubtsList: function(doubts, total, page, pageSize) {
        const list = $('#global-doubts-list');
        list.empty();
        
        if (doubts.length === 0) {
            list.html('<p class="text-muted text-center">No doubts found.</p>');
            $('#global-doubts-pagination').empty();
            return;
        }
        
        const AUTO_DOUBT_TEXTS = ["Auto takeaways", "Maximize Learning and Perspectives", "Challenge & Verify", "Foundations & Practice", "Answer Raised Questions"];
        
        doubts.forEach(d => {
            const isAuto = AUTO_DOUBT_TEXTS.some(t => d.doubt_text.startsWith(t));
            const badge = isAuto ? '<span class="badge badge-secondary ml-1">Auto</span>' : '';
            const pinBadge = d.pinned ? '<i class="bi bi-pin-fill text-primary mr-1"></i>' : '';
            const date = new Date(d.created_at).toLocaleDateString();
            const answerPreview = d.doubt_answer ? d.doubt_answer.substring(0, 120) + '...' : '';
            
            list.append(`
                <div class="card mb-2 global-doubt-card" data-doubt-id="${d.doubt_id}" data-conversation-id="${d.conversation_id}" style="cursor:pointer;">
                    <div class="card-body py-2 px-3">
                        <div class="d-flex justify-content-between">
                            <strong>${pinBadge}${d.doubt_text.substring(0, 80)}${d.doubt_text.length > 80 ? '...' : ''} ${badge}</strong>
                            <small class="text-muted">${date}</small>
                        </div>
                        <p class="mb-0 text-muted small">${answerPreview}</p>
                    </div>
                </div>
            `);
        });
        
        // Pagination
        const totalPages = Math.ceil(total / pageSize);
        const pag = $('#global-doubts-pagination');
        pag.empty();
        if (totalPages > 1) {
            for (let i = 1; i <= Math.min(totalPages, 10); i++) {
                pag.append(`<button class="btn btn-sm ${i === page ? 'btn-primary' : 'btn-outline-secondary'} mx-1 global-doubts-page-btn" data-page="${i}">${i}</button>`);
            }
        }
    },
    
    setupGlobalDoubtsHandlers: function() {
        const self = this;
        
        $('#global-doubts-btn').off('click').on('click', function() {
            self.openGlobalDoubtsModal();
        });
        
        // Search input with debounce
        let searchTimeout;
        $('#global-doubts-search').off('input').on('input', function() {
            clearTimeout(searchTimeout);
            searchTimeout = setTimeout(function() {
                self.globalDoubtsSearch = $('#global-doubts-search').val().trim();
                self.globalDoubtsPage = 1;
                self.loadGlobalDoubts();
            }, 400);
        });
        
        // Filter buttons
        $(document).off('click', '.global-doubts-filter').on('click', '.global-doubts-filter', function() {
            $('.global-doubts-filter').removeClass('active');
            $(this).addClass('active');
            self.globalDoubtsFilter = $(this).data('filter');
            self.globalDoubtsPage = 1;
            self.loadGlobalDoubts();
        });
        
        // Pagination
        $(document).off('click', '.global-doubts-page-btn').on('click', '.global-doubts-page-btn', function() {
            self.globalDoubtsPage = parseInt($(this).data('page'));
            self.loadGlobalDoubts();
        });
        
        // Click doubt card → navigate to conversation and open doubt
        $(document).off('click', '.global-doubt-card').on('click', '.global-doubt-card', function() {
            const doubtId = $(this).data('doubt-id');
            const conversationId = $(this).data('conversation-id');
            $('#global-doubts-modal').modal('hide');
            
            if (typeof ConversationManager !== 'undefined' && ConversationManager.loadConversation) {
                if (ConversationManager.activeConversationId === conversationId) {
                    // Same conversation — just open the doubt
                    self.openDoubtChat(doubtId);
                } else {
                    // Different conversation — load it, then open doubt after a delay
                    ConversationManager.loadConversation(conversationId);
                    setTimeout(function() { self.openDoubtChat(doubtId); }, 1500);
                }
            }
        });
    }
};

// Initialize when document is ready
$(document).ready(function() {
    console.log('DoubtManager initialized');
    DoubtManager.setupGlobalDoubtsHandlers();
}); 