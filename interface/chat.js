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
        
        persistSettingsStateFromModal();
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

    $('#settings-code-editor-modal-open-button').click(function () {
        // Directly open Code Editor modal
        $('#code-editor-modal').modal('show');
        if (typeof setupCodeEditor === 'function') {
            setupCodeEditor();
        }
    });

    // Ensure modal close buttons work
    $('#chat-settings-modal .close, #chat-settings-modal [data-dismiss="modal"]').click(function() {
        console.log('Closing chat settings modal');
        $('#chat-settings-modal').modal('hide');
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
    // Load persisted settings state on boot and apply to modal controls (and inline if present)
    initializeSettingsState();
});

// Settings Modal Functions
function loadSettingsIntoModal() {
    // Prefer persisted state if available; otherwise initialize from controls/defaults
    const state = getPersistedSettingsState() || buildSettingsStateFromControlsOrDefaults();
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
    const state = {
        perform_web_search: $('#chat-options-assistant-perform-web-search-checkbox').length ? $('#chat-options-assistant-perform-web-search-checkbox').is(':checked') : ($('#settings-perform-web-search-checkbox').is(':checked') || false),
        search_exact: $('#chat-options-assistant-search-exact').length ? $('#chat-options-assistant-search-exact').is(':checked') : ($('#settings-search-exact').is(':checked') || false),
        persist_or_not: $('#chat-options-assistant-persist_or_not').length ? $('#chat-options-assistant-persist_or_not').is(':checked') : ($('#settings-persist_or_not').is(':checked') || true),
        use_memory_pad: $('#use_memory_pad').length ? $('#use_memory_pad').is(':checked') : ($('#settings-use_memory_pad').is(':checked') || false),
        enable_planner: $('#enable_planner').length ? $('#enable_planner').is(':checked') : ($('#settings-enable_planner').is(':checked') || false),
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
    $('#settings-persist_or_not').prop('checked', state.persist_or_not !== false);
    $('#settings-use_memory_pad').prop('checked', !!state.use_memory_pad);
    $('#settings-enable_planner').prop('checked', !!state.enable_planner);
    $('#settings-ppt-answer').prop('checked', !!state.ppt_answer);
    $('#settings-depthSelector').val(state.depth || '2');
    $('#settings-historySelector').val(state.history || '2');
    $('#settings-rewardLevelSelector').val(state.reward || '0');
    $('#settings-preamble-selector').val(state.preamble_options || []);
    $('#settings-main-model-selector').val(state.main_model || []);
    $('#settings-field-selector').val(state.field || 'None');
    $('#settings-permanentText').val(state.permanentText || '');
    $('#settings-linkInput').val(state.links || '');
    $('#settings-searchInput').val(state.search || '');
}

function collectSettingsFromModal() {
    return {
        perform_web_search: $('#settings-perform-web-search-checkbox').is(':checked'),
        search_exact: $('#settings-search-exact').is(':checked'),
        persist_or_not: $('#settings-persist_or_not').is(':checked'),
        use_memory_pad: $('#settings-use_memory_pad').is(':checked'),
        enable_planner: $('#settings-enable_planner').is(':checked'),
        ppt_answer: $('#settings-ppt-answer').is(':checked'),
        depth: $('#settings-depthSelector').val() || '2',
        history: $('#settings-historySelector').val() || '2',
        reward: $('#settings-rewardLevelSelector').val() || '0',
        preamble_options: $('#settings-preamble-selector').val() || [],
        main_model: $('#settings-main-model-selector').val() || [],
        field: $('#settings-field-selector').val() || 'None',
        permanentText: $('#settings-permanentText').val() || '',
        links: $('#settings-linkInput').val() || '',
        search: $('#settings-searchInput').val() || ''
    };
}

function persistSettingsStateFromModal() {
    const tab = getCurrentActiveTab();
    const state = collectSettingsFromModal();
    window.chatSettingsState = state;
    try { 
        localStorage.setItem(`${tab}chatSettingsState`, JSON.stringify(state)); 
    } catch (e) { 
        console.error('Error saving chat settings to localStorage:', e); 
    }
    
}

function getPersistedSettingsState() {
    const tab = getCurrentActiveTab();
    
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

function initializeSettingsState() {
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
    $('#settings-persist_or_not').prop('checked', true);
    $('#settings-ppt-answer').prop('checked', false);
    $('#settings-use_memory_pad').prop('checked', false);
    $('#settings-enable_planner').prop('checked', false);
    
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
        case 'search':
            return ['Wife Prompt'];
        case 'finchat':
            return ['Short Coding Interview'];
        default:
            return ['Wife Prompt'];
    }
}

function getDefaultModelForTab(tab) {
    // All tabs use the same default model
    switch(tab) {
        case 'chat':
        case 'search':
            return ['Sonnet 4'];
        case 'finchat':
            return ['openai/gpt-5-chat'];
        default:
            return ['Sonnet 4'];
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
        persist_or_not: true,
        use_memory_pad: false,
        enable_planner: false,
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

