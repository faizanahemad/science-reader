// ---------- Settings Persistence Configuration ----------
// Set to false to disable saving settings to localStorage
// When disabled, settings will still work during the session but won't persist across page reloads
const ENABLE_SETTINGS_PERSISTENCE = true;

/**
 * Detects whether the current device is probably a mobile/touch-first device.
 *
 * Purpose:
 * - We need a stable, user-friendly default for certain UI features (like overriding
 *   the browser right-click context menu). On desktop we default it ON, while on
 *   mobile we default it OFF because long-press context menus and selection UX
 *   can be fragile and inconsistent.
 *
 * @returns {boolean} True if the device is likely mobile/touch-first, else false.
 */
function isProbablyMobileDevice() {
    try {
        // Pointer coarse is a good indicator of touch-first devices.
        if (window.matchMedia && window.matchMedia('(pointer: coarse)').matches) {
            return true;
        }
    } catch (e) {
        // Ignore matchMedia errors and fall back to UA/viewport heuristics.
    }
    const ua = (navigator && navigator.userAgent) ? navigator.userAgent : '';
    const uaMobile = /Mobi|Android|iPhone|iPad|iPod|IEMobile|Opera Mini/i.test(ua);
    const smallViewport = (typeof window !== 'undefined') ? (window.innerWidth <= 768) : false;
    return uaMobile || smallViewport;
}

// Expose globally for other modules loaded before chat.js (e.g., context-menu-manager.js)
window.isProbablyMobileDevice = isProbablyMobileDevice;

function chat_interface_readiness() {
    
    // $('#chat-assistant-view').hide();
    $("#loader").show();
    // loadConversations();
    // Hide the loader after 10 seconds
    setTimeout(function() {
        $("#loader").hide();
    }, 1000 * 1);  // 1000 milliseconds = 1 seconds
    
    $('#add-new-chat').on('click', function() {
        ConversationManager.createConversation();
    });
    setMaxHeightForTextbox('messageText', 10);
    setMaxHeightForTextbox("linkInput", 4);
    setMaxHeightForTextbox("searchInput", 4);
    function textboxCallBack(e) { // Add this block to submit the question on enter
        this_id = this.id
        if (e.which == 13 && !e.shiftKey && !e.altKey && window.innerWidth > 768) {
            if (this.id == 'messageText'){
                sendMessageCallback();
            }
            else {
                addNewlineToTextbox(this_id);
            }
            return false; // Prevents the default action
        }
        if ((e.keyCode == 13 && e.altKey) || (e.keyCode == 13 && e.shiftKey) || (e.which == 13 && window.innerWidth <= 768)) {
            addNewlineToTextbox(this_id);
            return false; // Prevents the default action
        }
        // REMOVED: Auto-scroll textarea to bottom - was causing unwanted scrolling in main chat view
        // if ((e.which != 13) && (e.which != 8) && (e.which != 46) && (e.which != 37) && (e.which != 38) && (e.which != 39) && (e.which != 40)) {
        //     var scrollHeight = $(this).prop('scrollHeight');
        //     var maxHeight = parseFloat($(this).css('max-height'));
        //     if(scrollHeight > maxHeight) {
        //         $(this).scrollTop(scrollHeight);
        //     }
        // }
    }
    $('#messageText').keypress(textboxCallBack);
    $('#messageText').on('input change', textboxCallBack);
    
    $('#sendMessageButton').on('click', sendMessageCallback);
    $('#stopResponseButton').on('click', stopCurrentResponse);
    $('#settings-clarifyDraftButton').on('click', function () {
        try {
            const already_rendering = $('#messageText').prop('working');
            if (already_rendering) {
                if (typeof showToast === 'function') {
                    showToast('Please wait for the current response to finish.', 'warning');
                } else {
                    alert('Please wait for the current response to finish.');
                }
                return;
            }
            const messageText = $('#messageText').val();
            if (!messageText || messageText.trim().length === 0) {
                if (typeof showToast === 'function') {
                    showToast('Please type a message first.', 'warning');
                } else {
                    alert('Please type a message first.');
                }
                return;
            }
            if (typeof ClarificationsManager === 'undefined' || typeof ClarificationsManager.requestAndShowClarifications !== 'function') {
                console.warn('ClarificationsManager not available.');
                return;
            }
            // Keep chat settings modal open/closed state as-is; show clarifications modal on top.
            ClarificationsManager.requestAndShowClarifications(ConversationManager.activeConversationId, messageText);
        } catch (e) {
            console.error('Clarify draft click handler error:', e);
        }
    });
    $('#stop-hint-button').on('click', stopCodingHint);
    $('#stop-solution-button').on('click', stopCodingSolution);
    $('#stop-doubt-chat-button').on('click', stopDoubtClearing);
    $('.dynamic-textarea').on('input change', function() {
      if ($(this).val().length === 0) {
          // If the textarea is empty, reset to the default height of 30px
          this.style.height = '35px';
      } else {
        
          this.style.height = 'auto'; // Reset height to auto to recalculate
          this.style.height = (this.scrollHeight) + 'px'; // Set the new height based on content
      }
    });
    // Chat Settings Modal Handler
    $('#chatSettingsButton').click(function () {
        console.log('Chat settings button clicked');
        // Ensure modal reflects latest saved state (if any)
        loadSettingsIntoModal();
        // Show the modal with proper configuration
        $('#chat-settings-modal').modal({
            backdrop: true,
            keyboard: true,
            focus: true,
            show: true
        });
        
        // Ensure modal is properly focused and clickable
        setTimeout(function() {
            $('#chat-settings-modal').focus();
            console.log('Chat settings modal should be visible');
        }, 100);
    });

    // Handle modal events for debugging and auto-apply
    $('#chat-settings-modal').on('shown.bs.modal', function () {
        console.log('Chat settings modal shown');
        $(this).focus();
    });

    $('#chat-settings-modal').on('hidden.bs.modal', function () {
        console.log('Chat settings modal hidden - auto-applying settings');
        // Auto-apply settings when modal closes and persist to state/localStorage
        // Use a small delay to ensure SelectPicker has synced its state to the 
        // underlying select elements, especially important on mobile devices
        setTimeout(function() {
            persistSettingsStateFromModal();
        }, 100);
    });

    // Apply button removed - settings auto-apply when modal closes

    // Settings Modal Reset Button Handler
    $('#settings-reset-button').click(function () {
        resetSettingsToDefaults();
        persistSettingsStateFromModal();
    });

    // Settings Modal Button Handlers (delegate to original buttons)
    $('#settings-deleteLastTurn').click(function () {
        if (ConversationManager.activeConversationId) {
            ChatManager.deleteLastMessage(ConversationManager.activeConversationId);
        }
    });

    $('#settings-memory-pad-text-open-button').click(function () {
        // Directly open Memory Pad modal
        // Load memory pad content first
        if (typeof ConversationManager !== 'undefined' && ConversationManager.loadMemoryPadText) {
            ConversationManager.loadMemoryPadText();
        }
        $('#memory-pad-modal').modal('show');
    });

    $('#settings-user-details-modal-open-button').click(function () {
        // Directly open User Details modal
        fetchUserDetail().then(function() {
            $('#user-details-modal').modal('show');
        });
    });

    $('#settings-user-preferences-modal-open-button').click(function () {
        // Directly open User Preferences modal
        fetchUserPreference().then(function() {
            $('#user-preferences-modal').modal('show');
        });
    });

    // Clear Locks button handler
    $('#settings-clear-locks-modal-open-button').click(function () {
        // Get conversation ID from ConversationManager
        const conversationId = typeof ConversationManager !== 'undefined' ? ConversationManager.activeConversationId : null;
        
        if (!conversationId) {
            alert('No active conversation. Please open a conversation first.');
            return;
        }
        
        // Show loading state
        $('#lock-status-content').html(
            '<div class="text-center">' +
            '<div class="spinner-border" role="status"><span class="sr-only">Loading...</span></div>' +
            '<p class="mt-2">Checking lock status...</p>' +
            '</div>'
        );
        $('#lock-clear-button').hide();
        $('#clear-locks-modal').modal('show');
        
        // Fetch lock status
        fetch(`/get_lock_status/${conversationId}`, {
            method: 'GET',
            headers: { 'Content-Type': 'application/json' }
        })
        .then(response => response.json())
        .then(data => {
            displayLockStatus(data, conversationId);
        })
        .catch(error => {
            console.error('Error fetching lock status:', error);
            $('#lock-status-content').html(
                '<div class="alert alert-danger"><i class="fa fa-exclamation-circle"></i> Error loading lock status: ' + error + '</div>'
            );
        });
    });

    // Lock clear button handler
    $('#lock-clear-button').click(function () {
        const conversationId = typeof ConversationManager !== 'undefined' ? ConversationManager.activeConversationId : null;
        
        if (!conversationId) {
            alert('No active conversation');
            return;
        }
        
        if (!confirm('Clear stuck locks? This should only be done if locks are preventing normal operation.')) {
            return;
        }
        
        // Show loading state
        $('#lock-status-content').html(
            '<div class="text-center">' +
            '<div class="spinner-border" role="status"><span class="sr-only">Clearing...</span></div>' +
            '<p class="mt-2">Clearing locks...</p>' +
            '</div>'
        );
        
        fetch(`/ensure_locks_cleared/${conversationId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                const clearedList = data.cleared.length > 0 ? data.cleared.join(', ') : 'None';
                $('#lock-status-content').html(
                    '<div class="alert alert-success">' +
                    '<i class="fa fa-check-circle"></i> <strong>Locks cleared successfully!</strong><br>' +
                    '<small>Cleared: ' + clearedList + '</small>' +
                    '</div>'
                );
                $('#lock-clear-button').hide();
                
                // Refresh status after 2 seconds
                setTimeout(function() {
                    $('#settings-clear-locks-modal-open-button').click();
                }, 2000);
            } else {
                $('#lock-status-content').html(
                    '<div class="alert alert-warning"><i class="fa fa-exclamation-triangle"></i> Could not clear all locks: ' + data.message + '</div>'
                );
            }
        })
        .catch(error => {
            console.error('Error clearing locks:', error);
            $('#lock-status-content').html(
                '<div class="alert alert-danger"><i class="fa fa-exclamation-circle"></i> Error clearing locks: ' + error + '</div>'
            );
        });
    });

    $('#settings-code-editor-modal-open-button').click(function () {
        // Directly open Code Editor modal
        $('#code-editor-modal').modal('show');
        if (typeof setupCodeEditor === 'function') {
            setupCodeEditor();
        }
    });

    $('#settings-artefacts-modal-open-button').click(function () {
        if (typeof ArtefactsManager !== 'undefined') {
            ArtefactsManager.openModal();
        } else {
            showToast('Artefacts manager not loaded', 'error');
        }
    });

    $('#settings-model-overrides-modal-open-button').click(function () {
        if (!ConversationManager.activeConversationId) {
            showToast('Select a conversation first', 'warning');
            return;
        }
        loadConversationModelOverrides(ConversationManager.activeConversationId);
    });

    // Ensure modal close buttons work
    $('#chat-settings-modal .close, #chat-settings-modal [data-dismiss="modal"]').click(function() {
        console.log('Closing chat settings modal');
        $('#chat-settings-modal').modal('hide');
    });

    $('#settings-model-overrides-save-button').click(function () {
        if (!ConversationManager.activeConversationId) {
            showToast('Select a conversation first', 'warning');
            return;
        }
        saveConversationModelOverrides(ConversationManager.activeConversationId);
    });

    $('#model-overrides-modal').on('shown.bs.modal', function () {
        $('#settings-summary-model').trigger('focus');
    });

    // Handle escape key
    $(document).keydown(function(e) {
        if (e.keyCode === 27 && $('#chat-settings-modal').hasClass('show')) { // ESC key
            $('#chat-settings-modal').modal('hide');
        }
    });

    // Listen for tab changes to reset settings to that tab's defaults
    $('#assistant-tab, #search-tab, #finchat-tab').on('shown.bs.tab', function () {
        const tab = getCurrentActiveTab();
        const defaultsForTab = getPersistedSettingsState() || computeDefaultStateForTab(tab);
        window.chatSettingsState = defaultsForTab;
        setModalFromState(defaultsForTab);
        if (window.chatSettingsState && window.chatSettingsState.model_overrides) {
            ConversationManager.conversationSettings = {
                model_overrides: window.chatSettingsState.model_overrides
            };
        }
        if (typeof $.fn.selectpicker !== 'undefined') { $('.selectpicker').selectpicker('refresh'); }
    });



    $('#toggleChatDocsView').click(function () {
        $('#chat-doc-view').toggleClass('d-none');
        // ▲ ▼
        // change inner content of the button based on current content
        var currentContent = $(this).text();
        var newContent = currentContent === '▲' ? '▼' : '▲';
        $(this).text(newContent);
    });
    // REMOVED: Auto-scroll on page initialization - was interrupting user reading
    // $(window).scrollTop(0);
    scrollToBottom();

    $('#memory-pad-text-open-button').click(function() {
        $('#memory-pad-modal').modal('show');
    });

    $('#memory-pad-text-save-button').click(function() {
        // get text from textarea with id as memory-pad-text
        var text = $('#memory-pad-text').val();
        ConversationManager.saveMemoryPadText(text);
        $('#memory-pad-modal').modal('hide');
    });
    // $('#toggleChatDocsView').click();

    // User Details and Preferences API functions
    function fetchUserDetail() {
        return $.ajax({
            url: '/get_user_detail',
            type: 'GET',
            success: function(result) {
                $('#user-details-text').val(result.text);
            },
            error: function(xhr) {
                console.error('Error fetching user details:', xhr.responseText);
                // Optionally show an error message
                // alert('Failed to load user details');
            }
        });
    }

    function saveUserDetail(text) {
        return $.ajax({
            url: '/modify_user_detail',
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ 'text': text }),
            success: function(result) {
                console.log('User details saved successfully');
            },
            error: function(xhr) {
                console.error('Error saving user details:', xhr.responseText);
                alert('Error: Failed to save user details');
            }
        });
    }

    function fetchUserPreference() {
        return $.ajax({
            url: '/get_user_preference',
            type: 'GET',
            success: function(result) {
                $('#user-preferences-text').val(result.text);
            },
            error: function(xhr) {
                console.error('Error fetching user preferences:', xhr.responseText);
                // Optionally show an error message
                // alert('Failed to load user preferences');
            }
        });
    }

    function saveUserPreference(text) {
        return $.ajax({
            url: '/modify_user_preference',
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ 'text': text }),
            success: function(result) {
                console.log('User preferences saved successfully');
            },
            error: function(xhr) {
                console.error('Error saving user preferences:', xhr.responseText);
                alert('Error: Failed to save user preferences');
            }
        });
    }

    // Event handlers for User Details modal
    $('#user-details-modal-open-button').click(function() {
        // Fetch user details before showing the modal
        fetchUserDetail().then(function() {
            $('#user-details-modal').modal('show');
        });
    });

    $('#user-details-text-save-button').click(function() {
        var text = $('#user-details-text').val();
        saveUserDetail(text);
        $('#user-details-modal').modal('hide');
    });

    // Event handlers for User Preferences modal
    $('#user-preferences-modal-open-button').click(function() {
        // Fetch user preferences before showing the modal
        fetchUserPreference().then(function() {
            $('#user-preferences-modal').modal('show');
        });
    });

    $('#user-preferences-text-save-button').click(function() {
        var text = $('#user-preferences-text').val();
        saveUserPreference(text);
        $('#user-preferences-modal').modal('hide');
    });
    initializeGamificationSystem();

    renderMermaidIfDetailsTagOpened();
    
}

$(document).ready(function() {
    chat_interface_readiness();
    interface_readiness();
    setupCodeEditor();
    loadModelCatalog();
    // Load persisted settings state on boot and apply to modal controls (and inline if present)
    initializeSettingsState();
    
    // Ensure custom prompts are populated after DOM is ready
    // Use a small delay to ensure modal HTML is fully loaded
    setTimeout(function() {
        populateCustomPromptsInDOM();
        // Re-apply persisted preamble options if they exist
        if (window.chatSettingsState && window.chatSettingsState.preamble_options) {
            $('#settings-preamble-selector').val(window.chatSettingsState.preamble_options);
        }
    }, 100);
});

// Settings Modal Functions
function loadSettingsIntoModal() {
    // Prefer persisted state if available; otherwise initialize from controls/defaults
    const state = getPersistedSettingsState() || buildSettingsStateFromControlsOrDefaults();
    
    // Ensure custom prompts are populated before setting state
    populateCustomPromptsInDOM();
    
    setModalFromState(state);
    // Refresh select pickers after loading values
    if (typeof $.fn.selectpicker !== 'undefined') {
        $('#settings-preamble-selector, #settings-main-model-selector').selectpicker('refresh');
    }
}



// ---------- Settings State Persistence ----------
function buildSettingsStateFromControlsOrDefaults() {
    // Fallback builder used on first run when no state exists
    const currentTab = getCurrentActiveTab();
    const defaultEnableCustomContextMenu = !isProbablyMobileDevice();
    const state = {
        perform_web_search: $('#chat-options-assistant-perform-web-search-checkbox').length ? $('#chat-options-assistant-perform-web-search-checkbox').is(':checked') : ($('#settings-perform-web-search-checkbox').is(':checked') || false),
        search_exact: $('#chat-options-assistant-search-exact').length ? $('#chat-options-assistant-search-exact').is(':checked') : ($('#settings-search-exact').is(':checked') || false),
        auto_clarify: $('#chat-options-assistant-auto_clarify').length ? $('#chat-options-assistant-auto_clarify').is(':checked') : ($('#settings-auto_clarify').is(':checked') || false),
        persist_or_not: $('#chat-options-assistant-persist_or_not').length ? $('#chat-options-assistant-persist_or_not').is(':checked') : ($('#settings-persist_or_not').is(':checked') || true),
        use_memory_pad: $('#use_memory_pad').length ? $('#use_memory_pad').is(':checked') : ($('#settings-use_memory_pad').is(':checked') || false),
        enable_planner: $('#enable_planner').length ? $('#enable_planner').is(':checked') : ($('#settings-enable_planner').is(':checked') || false),
        enable_custom_context_menu: defaultEnableCustomContextMenu,
        ppt_answer: $('#settings-ppt-answer').is(':checked') || false,
        depth: $('#depthSelector').length ? $('#depthSelector').val() : ($('#settings-depthSelector').val() || '2'),
        history: $('#historySelector').length ? $('#historySelector').val() : ($('#settings-historySelector').val() || '2'),
        reward: $('#rewardLevelSelector').length ? $('#rewardLevelSelector').val() : ($('#settings-rewardLevelSelector').val() || '0'),
        preamble_options: $('#preamble-selector').length ? $('#preamble-selector').val() : (getDefaultPreambleForTab(currentTab)),
        main_model: $('#main-model-selector').length ? $('#main-model-selector').val() : (getDefaultModelForTab(currentTab)),
        field: $('#field-selector').length ? $('#field-selector').val() : (getDefaultAgentForTab(currentTab)),
        permanentText: $('#permanentText').length ? $('#permanentText').val() : ($('#settings-permanentText').val() || ''),
        links: $('#linkInput').length ? $('#linkInput').val() : ($('#settings-linkInput').val() || ''),
        search: $('#searchInput').length ? $('#searchInput').val() : ($('#settings-searchInput').val() || '')
    };
    return state;
}

function setModalFromState(state) {
    if (!state) { return; }
    $('#settings-perform-web-search-checkbox').prop('checked', !!state.perform_web_search);
    $('#settings-search-exact').prop('checked', !!state.search_exact);
    $('#settings-auto_clarify').prop('checked', !!state.auto_clarify);
    $('#settings-persist_or_not').prop('checked', state.persist_or_not !== false);
    $('#settings-use_memory_pad').prop('checked', !!state.use_memory_pad);
    $('#settings-enable_planner').prop('checked', !!state.enable_planner);
    $('#settings-enable_custom_context_menu').prop(
        'checked',
        (state.enable_custom_context_menu !== undefined && state.enable_custom_context_menu !== null)
            ? !!state.enable_custom_context_menu
            : !isProbablyMobileDevice()
    );
    $('#settings-ppt-answer').prop('checked', !!state.ppt_answer);
    $('#settings-depthSelector').val(state.depth || '2');
    $('#settings-historySelector').val(state.history || '2');
    $('#settings-rewardLevelSelector').val(state.reward || '0');
    
    // Handle preamble options including custom prompts
    const preambleOptions = state.preamble_options || [];
    
    // Populate custom prompts in DOM if available
    populateCustomPromptsInDOM();
    
    $('#settings-preamble-selector').val(preambleOptions);
    $('#settings-main-model-selector').val(state.main_model || []);
    $('#settings-field-selector').val(state.field || 'None');
    $('#settings-permanentText').val(state.permanentText || '');
    $('#settings-linkInput').val(state.links || '');
    $('#settings-searchInput').val(state.search || '');
}

function populateCustomPromptsInDOM() {
    // Check if we have custom prompts in cache and the DOM element exists
    if (window.availableCustomPrompts && window.availableCustomPrompts.length > 0) {
        const customPromptsGroup = $('#custom-prompts-group');
        if (customPromptsGroup.length) {
            // Clear and repopulate to ensure freshness
            customPromptsGroup.empty();
            window.availableCustomPrompts.forEach(prompt => {
                const option = $('<option></option>')
                    .val(prompt.value)
                    .text(prompt.displayName);
                customPromptsGroup.append(option);
            });
            console.log(`Populated ${window.availableCustomPrompts.length} custom prompts in DOM`);
        }
    }
}

/**
 * Helper function to get the current value from a SelectPicker element.
 * SelectPicker maintains its own UI state that may not be immediately synced 
 * to the underlying <select> element. This function ensures we get the current
 * visible selection, not a stale cached value.
 * 
 * @param {string} selector - jQuery selector for the select element
 * @param {*} defaultValue - Default value if nothing is selected
 * @returns {*} The current selected value(s)
 */
function getSelectPickerValue(selector, defaultValue) {
    const $el = $(selector);
    if (!$el.length) {
        return defaultValue;
    }
    
    // Check if SelectPicker is initialized on this element
    if (typeof $.fn.selectpicker !== 'undefined' && $el.data('selectpicker')) {
        // Force sync the SelectPicker state to the underlying select element
        $el.selectpicker('refresh');
        // Use SelectPicker's val method which reads from its internal state
        const val = $el.selectpicker('val');
        return val !== null && val !== undefined ? val : defaultValue;
    }
    
    // Fallback for non-SelectPicker selects
    return $el.val() || defaultValue;
}

function collectSettingsFromModal() {
    // Force SelectPicker elements to sync their state before reading values
    // This fixes a bug where deselected options (like "Filler") would remain
    // in the saved state because SelectPicker hadn't synced to the <select> element
    if (typeof $.fn.selectpicker !== 'undefined') {
        $('#settings-preamble-selector, #settings-main-model-selector').selectpicker('refresh');
    }
    
    return {
        perform_web_search: $('#settings-perform-web-search-checkbox').is(':checked'),
        search_exact: $('#settings-search-exact').is(':checked'),
        auto_clarify: $('#settings-auto_clarify').is(':checked'),
        persist_or_not: $('#settings-persist_or_not').is(':checked'),
        use_memory_pad: $('#settings-use_memory_pad').is(':checked'),
        enable_planner: $('#settings-enable_planner').is(':checked'),
        enable_custom_context_menu: $('#settings-enable_custom_context_menu').is(':checked'),
        ppt_answer: $('#settings-ppt-answer').is(':checked'),
        depth: $('#settings-depthSelector').val() || '2',
        history: $('#settings-historySelector').val() || '2',
        reward: $('#settings-rewardLevelSelector').val() || '0',
        preamble_options: getSelectPickerValue('#settings-preamble-selector', []),
        main_model: getSelectPickerValue('#settings-main-model-selector', []),
        field: $('#settings-field-selector').val() || 'None',
        permanentText: $('#settings-permanentText').val() || '',
        links: $('#settings-linkInput').val() || '',
        search: $('#settings-searchInput').val() || '',
        model_overrides: (window.chatSettingsState && window.chatSettingsState.model_overrides)
            ? window.chatSettingsState.model_overrides
            : undefined
    };
}

/**
 * Persists the current modal settings to window state and optionally to localStorage.
 * The localStorage persistence is controlled by the ENABLE_SETTINGS_PERSISTENCE flag.
 * 
 * This function is called when the settings modal is closed to save the current selections.
 */
function persistSettingsStateFromModal() {
    const tab = getCurrentActiveTab();
    const state = collectSettingsFromModal();
    
    // Always update the in-memory state for the current session
    window.chatSettingsState = state;
    
    // Only persist to localStorage if the flag is enabled
    if (ENABLE_SETTINGS_PERSISTENCE) {
        try { 
            localStorage.setItem(`${tab}chatSettingsState`, JSON.stringify(state));
            console.log('Settings persisted to localStorage for tab:', tab);
        } catch (e) { 
            console.error('Error saving chat settings to localStorage:', e); 
        }
    } else {
        console.log('Settings persistence disabled, only in-memory state updated');
    }
}

function loadConversationModelOverrides(conversationId) {
    loadModelCatalog(function () {
        populateModelOverrideOptions();
        $.ajax({
            url: '/get_conversation_settings/' + conversationId,
            type: 'GET',
            success: function (result) {
                var settings = (result && result.settings) ? result.settings : {};
                ConversationManager.conversationSettings = settings;
                var overrides = settings.model_overrides || {};
                setModelOverrideValue('#settings-summary-model', overrides.summary_model || '', DEFAULT_MODEL_OVERRIDES.summary_model);
                setModelOverrideValue('#settings-tldr-model', overrides.tldr_model || '', DEFAULT_MODEL_OVERRIDES.tldr_model);
                setModelOverrideValue('#settings-artefact-propose-model', overrides.artefact_propose_edits_model || '', DEFAULT_MODEL_OVERRIDES.artefact_propose_edits_model);
                setModelOverrideValue('#settings-doubt-clearing-model', overrides.doubt_clearing_model || '', DEFAULT_MODEL_OVERRIDES.doubt_clearing_model);
                setModelOverrideValue('#settings-context-action-model', overrides.context_action_model || '', DEFAULT_MODEL_OVERRIDES.context_action_model);
                setModelOverrideValue('#settings-doc-long-summary-model', overrides.doc_long_summary_model || '', DEFAULT_MODEL_OVERRIDES.doc_long_summary_model);
                setModelOverrideValue('#settings-doc-long-summary-v2-model', overrides.doc_long_summary_v2_model || '', DEFAULT_MODEL_OVERRIDES.doc_long_summary_v2_model);
                setModelOverrideValue('#settings-doc-short-answer-model', overrides.doc_short_answer_model || '', DEFAULT_MODEL_OVERRIDES.doc_short_answer_model);
                $('#model-overrides-modal').modal('show');
            },
            error: function (xhr) {
                console.error('Error loading conversation settings:', xhr.responseText);
                showToast('Failed to load model overrides', 'error');
            }
        });
    });
}

function saveConversationModelOverrides(conversationId) {
    var overrides = {
        summary_model: getModelOverrideValue('#settings-summary-model'),
        tldr_model: getModelOverrideValue('#settings-tldr-model'),
        artefact_propose_edits_model: getModelOverrideValue('#settings-artefact-propose-model'),
        doubt_clearing_model: getModelOverrideValue('#settings-doubt-clearing-model'),
        context_action_model: getModelOverrideValue('#settings-context-action-model'),
        doc_long_summary_model: getModelOverrideValue('#settings-doc-long-summary-model'),
        doc_long_summary_v2_model: getModelOverrideValue('#settings-doc-long-summary-v2-model'),
        doc_short_answer_model: getModelOverrideValue('#settings-doc-short-answer-model')
    };
    Object.keys(overrides).forEach(function (key) {
        if (!overrides[key]) {
            delete overrides[key];
        }
    });
    $.ajax({
        url: '/set_conversation_settings/' + conversationId,
        type: 'PUT',
        contentType: 'application/json',
        data: JSON.stringify({ model_overrides: overrides }),
        success: function () {
            ConversationManager.conversationSettings = { model_overrides: overrides };
            if (window.chatSettingsState) {
                window.chatSettingsState.model_overrides = overrides;
            }
            showToast('Model overrides saved', 'success');
            $('#model-overrides-modal').modal('hide');
        },
        error: function (xhr) {
            console.error('Error saving conversation settings:', xhr.responseText);
            showToast('Failed to save model overrides', 'error');
        }
    });
}

var DEFAULT_MODEL_OVERRIDES = {};

function getModelOverrideValue(selector) {
    const selected = ($(selector).val() || '').trim();
    const defaultValue = DEFAULT_MODEL_OVERRIDES[$(selector).attr('id').replace('settings-', '').replace(/-/g, '_')] || '';
    if (!selected || selected === '__default__') {
        return '';
    }
    return selected === defaultValue ? '' : selected;
}

function setModelOverrideValue(selector, overrideValue, defaultValue) {
    if (overrideValue) {
        $(selector).val(overrideValue);
        return;
    }
    $(selector).val(defaultValue || '__default__');
}

function populateModelOverrideOptions() {
    const modelList = window.ModelCatalog && window.ModelCatalog.getAll
        ? window.ModelCatalog.getAll()
        : [];
    const selects = [
        '#settings-summary-model',
        '#settings-tldr-model',
        '#settings-artefact-propose-model',
        '#settings-doubt-clearing-model',
        '#settings-context-action-model',
        '#settings-doc-long-summary-model',
        '#settings-doc-long-summary-v2-model',
        '#settings-doc-short-answer-model'
    ];
    selects.forEach(function (selector) {
        const $select = $(selector);
        if (!$select.length) {
            return;
        }
        const current = $select.val();
        const key = $select.attr('id')
            .replace('settings-', '')
            .replace(/-/g, '_');
        const defaultValue = DEFAULT_MODEL_OVERRIDES[key] || '';
        $select.empty();
        $select.append(new Option('Default (recommended)', '__default__'));
        if (defaultValue) {
            $select.append(new Option(defaultValue + ' (default)', defaultValue));
        }
        modelList.forEach(function (model) {
            if (model === defaultValue) {
                return;
            }
            $select.append(new Option(model, model));
        });
        if (current) {
            $select.val(current);
        }
    });
}

function loadModelCatalog(callback) {
    if (window.ModelCatalog && window.ModelCatalog.ready) {
        if (callback) {
            callback();
        }
        return;
    }
    $.ajax({
        url: '/model_catalog',
        type: 'GET',
        success: function (result) {
            window.ModelCatalog = {
                models: (result && result.models) ? result.models : [],
                defaults: (result && result.defaults) ? result.defaults : {},
                ready: true,
                getAll: function () { return this.models || []; }
            };
            DEFAULT_MODEL_OVERRIDES = window.ModelCatalog.defaults || {};
            if (callback) {
                callback();
            }
        },
        error: function (xhr) {
            console.error('Error loading model catalog:', xhr.responseText);
            window.ModelCatalog = {
                models: [],
                defaults: {},
                ready: true,
                getAll: function () { return this.models || []; }
            };
            DEFAULT_MODEL_OVERRIDES = {};
            if (callback) {
                callback();
            }
        }
    });
}

/**
 * Retrieves the persisted settings state from localStorage (if enabled) or returns
 * the current in-memory state.
 * 
 * @returns {Object|null} The settings state object or null if not found
 */
function getPersistedSettingsState() {
    const tab = getCurrentActiveTab();
    
    // If persistence is disabled, only return in-memory state
    if (!ENABLE_SETTINGS_PERSISTENCE) {
        return window.chatSettingsState || null;
    }
    
    try {
        const raw = localStorage.getItem(`${tab}chatSettingsState`);
        if (raw) { 
            window.chatSettingsState = JSON.parse(raw); 
        }
    } catch (e) { 
        console.error('Error getting chat settings from localStorage:', e); 
    }
    return window.chatSettingsState || null;
}

/**
 * Removes references to custom prompts that no longer exist from the saved settings.
 * This ensures that if a custom prompt is deleted, it doesn't remain selected in saved state.
 */
function cleanupDeletedCustomPrompts() {
    if (!window.chatSettingsState || !window.availableCustomPrompts) return;
    
    const availableCustomValues = window.availableCustomPrompts.map(p => p.value);
    const currentPreamble = window.chatSettingsState.preamble_options || [];
    
    // Filter out custom prompts that no longer exist
    const cleanedPreamble = currentPreamble.filter(option => {
        if (option.startsWith('custom:')) {
            return availableCustomValues.includes(option);
        }
        return true; // Keep all default prompts
    });
    
    if (cleanedPreamble.length !== currentPreamble.length) {
        window.chatSettingsState.preamble_options = cleanedPreamble;
        
        // Save the cleaned state back to localStorage only if persistence is enabled
        if (ENABLE_SETTINGS_PERSISTENCE) {
            const tab = getCurrentActiveTab();
            try {
                localStorage.setItem(`${tab}chatSettingsState`, JSON.stringify(window.chatSettingsState));
                console.log('Cleaned up deleted custom prompts from saved settings');
            } catch (e) {
                console.error('Error saving cleaned settings:', e);
            }
        }
    }
}

function loadCustomPromptsOnInit() {
    // Fetch custom prompts and store in global variable
    window.availableCustomPrompts = [];
    
    fetch('/get_prompts', {
        method: 'GET',
        headers: {'Content-Type': 'application/json'}
    })
    .then(response => response.json())
    .then(data => {
        if (data.status === 'success' && data.prompts) {
            // Apply the same filtering logic as loadCustomPrompts
            // Combine prompts and prompts_detailed arrays
            const combinedPrompts = data.prompts.map((promptName, index) => {
                const detailedInfo = data.prompts_detailed ? 
                    data.prompts_detailed.find(p => p.name === promptName) || {} : {};
                return {
                    name: promptName,
                    ...detailedInfo
                };
            });
            
            // Filter prompts that have empty category (or no category)
            const categorizedPrompts = combinedPrompts.filter(prompt => 
                !prompt.category || prompt.category.trim() === ''
            );
            
            // Update data to only include filtered prompts
            data.prompts = categorizedPrompts.map(prompt => prompt.name);
            
            // Filter custom prompts (non-default ones)
            const defaultPrompts = [
                'No Links', 'Wife Prompt', 'Debug LLM', 'Short', 
                'Short Coding Interview', 'No Code', 'ML Design Answer Short',
                'Argumentative', 'Blackmail', 'More Related Coding Questions',
                'Diagram', 'Easy Copy', 'Creative', 'Explore',
                'Relationship', 'Dating Maverick'
            ];
            const defaultPromptKeys = defaultPrompts.map(p => 
                p.toLowerCase().replace(/ /g, '_')
            );
            
            data.prompts.forEach(promptName => {
                if (!defaultPromptKeys.includes(promptName.toLowerCase())) {
                    window.availableCustomPrompts.push({
                        name: promptName,
                        value: `custom:${promptName}`,
                        displayName: promptName.replace(/_/g, ' ')
                            .replace(/\b\w/g, l => l.toUpperCase())
                    });
                }
            });
            
            // Clean up any deleted prompts from saved settings
            cleanupDeletedCustomPrompts();
            
            // Try to populate DOM with custom prompts (in case modal HTML is ready)
            populateCustomPromptsInDOM();
            
            // Also update the selector value if we have persisted state
            if (window.chatSettingsState && window.chatSettingsState.preamble_options) {
                $('#settings-preamble-selector').val(window.chatSettingsState.preamble_options);
            }
        }
    })
    .catch(error => {
        console.error('Error loading custom prompts on init:', error);
    });
}

function initializeSettingsState() {
    // Load custom prompts early so they're available immediately
    loadCustomPromptsOnInit();
    
    const state = getPersistedSettingsState();
    window.chatSettingsState = state;
    if (state) {
        // Ensure modal controls reflect persisted state now
        setModalFromState(state);
        
        // Also apply to inline controls if present
        if ($('#depthSelector').length) { $('#depthSelector').val(state.depth || '2'); }
        if ($('#historySelector').length) { $('#historySelector').val(state.history || '2'); }
        if ($('#rewardLevelSelector').length) { $('#rewardLevelSelector').val(state.reward || '0'); }
        if ($('#chat-options-assistant-perform-web-search-checkbox').length) { $('#chat-options-assistant-perform-web-search-checkbox').prop('checked', !!state.perform_web_search); }
        if ($('#chat-options-assistant-search-exact').length) { $('#chat-options-assistant-search-exact').prop('checked', !!state.search_exact); }
        if ($('#chat-options-assistant-persist_or_not').length) { $('#chat-options-assistant-persist_or_not').prop('checked', state.persist_or_not !== false); }
        if ($('#use_memory_pad').length) { $('#use_memory_pad').prop('checked', !!state.use_memory_pad); }
        if (typeof $.fn.selectpicker !== 'undefined') { $('.selectpicker').selectpicker('refresh'); }
    }
}

function resetSettingsToDefaults() {
    // Reset all settings to their default values
    
    // Basic Options
    $('#settings-perform-web-search-checkbox').prop('checked', false);
    $('#settings-search-exact').prop('checked', false);
    $('#settings-auto_clarify').prop('checked', false);
    $('#settings-persist_or_not').prop('checked', true);
    $('#settings-ppt-answer').prop('checked', false);
    $('#settings-use_memory_pad').prop('checked', false);
    $('#settings-enable_planner').prop('checked', false);
    $('#settings-enable_custom_context_menu').prop('checked', !isProbablyMobileDevice());
    
    // Advanced Settings
    $('#settings-depthSelector').val('2');
    $('#settings-historySelector').val('2');
    $('#settings-rewardLevelSelector').val('0');
    
    // Model and Agent Selection - use tab-based defaults
    var currentTab = getCurrentActiveTab();
    var defaultPreamble = getDefaultPreambleForTab(currentTab);
    var defaultModel = getDefaultModelForTab(currentTab);
    var defaultAgent = getDefaultAgentForTab(currentTab);
    
    $('#settings-preamble-selector').val(defaultPreamble);
    $('#settings-main-model-selector').val(defaultModel);
    $('#settings-field-selector').val(defaultAgent);
    
    // Permanent Instructions
    $('#settings-permanentText').val('');

    // Search & Links
    $('#settings-linkInput').val('');
    $('#settings-searchInput').val('');

    // Conversation model overrides (reset for UI state)
    if (window.chatSettingsState) {
        delete window.chatSettingsState.model_overrides;
    }

    // Refresh any select pickers if they exist
    if (typeof $.fn.selectpicker !== 'undefined') {
        $('.selectpicker').selectpicker('refresh');
    }
    
    console.log('Settings reset to defaults');
}

// Helper functions for tab-based defaults
function getCurrentActiveTab() {
    if ($('#chat-tab').hasClass('active')) return 'chat';
    if ($('#search-tab').hasClass('active')) return 'search';
    if ($('#finchat-tab').hasClass('active')) return 'finchat';
    return 'chat'; // default
}

function getDefaultPreambleForTab(tab) {
    switch(tab) {
        case 'chat':
            return ['Google GL'];
        case 'search':
            return ['Wife Prompt'];
        case 'finchat':
            return ['Wife Prompt'];
        default:
            return ['Wife Prompt'];
    }
}

function getDefaultModelForTab(tab) {
    // All tabs use the same default model
    switch(tab) {
        case 'chat':
        case 'search':
            return ['Sonnet 4.5'];
        case 'finchat':
            return ['Sonnet 4.5'];
        default:
            return ['Sonnet 4.5'];
    }
}

function getDefaultAgentForTab(tab) {
    // All tabs default to None
    return 'None';
}

// Build a full default state object for a given tab
function computeDefaultStateForTab(tab) {
    return {
        perform_web_search: false,
        search_exact: false,
        auto_clarify: false,
        persist_or_not: true,
        use_memory_pad: false,
        enable_planner: false,
        enable_custom_context_menu: !isProbablyMobileDevice(),
        ppt_answer: false,
        depth: '2',
        history: '2',
        reward: '0',
        preamble_options: getDefaultPreambleForTab(tab),
        main_model: getDefaultModelForTab(tab),
        field: getDefaultAgentForTab(tab),
        permanentText: '',
        links: '',
        search: ''
    };
}

/**
 * Clears all persisted chat settings from localStorage for all tabs.
 * Useful for debugging or forcing a fresh start.
 * Can be called from browser console: clearAllPersistedSettings()
 */
function clearAllPersistedSettings() {
    const tabs = ['chat', 'search', 'finchat'];
    tabs.forEach(tab => {
        try {
            localStorage.removeItem(`${tab}chatSettingsState`);
            console.log(`Cleared persisted settings for tab: ${tab}`);
        } catch (e) {
            console.error(`Error clearing settings for tab ${tab}:`, e);
        }
    });
    window.chatSettingsState = null;
    console.log('All persisted settings cleared. Refresh the page for defaults.');
}

/**
 * Clears persisted settings for the current tab only.
 * Can be called from browser console: clearCurrentTabSettings()
 */
function clearCurrentTabSettings() {
    const tab = getCurrentActiveTab();
    try {
        localStorage.removeItem(`${tab}chatSettingsState`);
        window.chatSettingsState = null;
        console.log(`Cleared persisted settings for current tab: ${tab}`);
    } catch (e) {
        console.error('Error clearing current tab settings:', e);
    }
}

/**
 * Displays lock status information in the Clear Locks modal.
 * @param {Object} data - Lock status data from the API
 * @param {string} conversationId - Current conversation ID
 */
function displayLockStatus(data, conversationId) {
    let html = '<div>';
    
    // Overall status banner
    if (data.any_locked) {
        html += '<div class="alert alert-warning">';
        html += '<i class="fa fa-exclamation-triangle"></i> <strong>Some locks are currently held</strong>';
        html += '</div>';
    } else {
        html += '<div class="alert alert-success">';
        html += '<i class="fa fa-check-circle"></i> <strong>All locks are clear</strong>';
        html += '</div>';
    }
    
    // Conversation ID
    html += '<p class="text-muted small mb-2">Conversation: <code>' + conversationId + '</code></p>';
    
    // Lock status table
    html += '<h6 class="mb-2">Lock Status:</h6>';
    html += '<table class="table table-sm table-bordered">';
    html += '<thead class="thead-light"><tr><th>Lock Type</th><th>Status</th></tr></thead>';
    html += '<tbody>';
    
    const lockLabels = {
        '': 'Main Lock',
        'all': 'All Fields',
        'message_operations': 'Message Operations',
        'memory': 'Memory',
        'messages': 'Messages',
        'uploaded_documents_list': 'Documents List'
    };
    
    for (const [lockKey, isLocked] of Object.entries(data.locks_status || {})) {
        const status = isLocked 
            ? '<span class="badge badge-warning"><i class="fa fa-lock"></i> HELD</span>' 
            : '<span class="badge badge-success"><i class="fa fa-unlock"></i> CLEAR</span>';
        const displayKey = lockLabels[lockKey] || lockKey || '(main)';
        html += '<tr><td>' + displayKey + '</td><td>' + status + '</td></tr>';
    }
    
    html += '</tbody></table>';
    
    // Stale locks warning
    if (data.stale_locks && data.stale_locks.length > 0) {
        html += '<div class="alert alert-danger mt-3">';
        html += '<strong><i class="fa fa-exclamation-circle"></i> Stale Locks Detected:</strong>';
        html += '<ul class="mb-0 mt-2">';
        data.stale_locks.forEach(function(lock) {
            html += '<li><code>' + lock + '</code></li>';
        });
        html += '</ul>';
        html += '<p class="mb-0 mt-2 small">These locks appear abandoned and can be safely cleared.</p>';
        html += '</div>';
    }
    
    // Help text
    if (!data.any_locked && (!data.stale_locks || data.stale_locks.length === 0)) {
        html += '<p class="text-muted small mt-3 mb-0">';
        html += '<i class="fa fa-info-circle"></i> No action needed. All locks are clear.';
        html += '</p>';
    }
    
    html += '</div>';
    
    $('#lock-status-content').html(html);
    
    // Show clear button if there are locks to clear
    if (data.any_locked || (data.stale_locks && data.stale_locks.length > 0)) {
        $('#lock-clear-button').show();
    } else {
        $('#lock-clear-button').hide();
    }
}
