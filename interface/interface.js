var userDetails = {
    email: null,
    name: null
}

function interface_readiness() {
    const options = {
        throwOnError: false,
        trust: true
    };
    
    var activeDocId = localStorage.getItem('activeDocId') || null;
    var pdfUrl = null;
    
    
    
    
    

    function toggleSidebar() {
        function getActiveTabName() {
            var activeTab = $('#pdf-details-tab .nav-link.active').attr('id');
            return activeTab;
        }
        var activeTabName = getActiveTabName();

        if (activeTabName === 'assistant-tab' || activeTabName === 'search-tab' || activeTabName === 'finchat-tab') {
            var sidebar = $('#chat-assistant-sidebar');
            
            var contentCol = $('#chat-assistant');
        } 
        if (sidebar.is(':visible')) {
            // If the sidebar is currently visible, hide it
            sidebar.addClass('d-none');

            // Adjust the width of the content column
            contentCol.removeClass('col-md-10').addClass('col-md-12');
            // REMOVED: Auto-scroll to top when hiding sidebar - was interrupting user reading
            // $(document).scrollTop(0);
            // // scroll to the top of the page for the window
            // $(window).scrollTop(0);
        } else {
            // If the sidebar is currently hidden, show it
            sidebar.removeClass('d-none');

            // Adjust the width of the content column
            contentCol.removeClass('col-md-12').addClass('col-md-10');
        }

        // Trigger the resize event to adjust the size of the PDF viewer
        $(window).trigger('resize');
    }

    
    
    function showUserName(){
        $.get('/get_user_info', function(data) {
            $('#username').text(data.name.slice(0, 10));
            userDetails.email = data.email;
            userDetails.name = data.name;
        });
    }

    $('#logout-link').on('click', function(e) {
        e.preventDefault();
        clearSwCaches()
            .then(function() { console.log('[Logout] caches cleared, redirecting'); })
            .catch(function(err) { console.warn('[Logout] cache clear error:', err); })
            .then(function() { window.location.href = '/logout'; });
    });
    


    
    showUserName();
    
    

    $('#assistant-tab').on('click', function () { 
        $("#chat-pdf-content").addClass('d-none'); 
        $("#chat-content").removeClass('d-none');
        currentDomain["manual_domain_change"] = true;
    })
    $('#search-tab').on('click', function () { 
        $("#chat-pdf-content").addClass('d-none'); 
        $("#chat-content").removeClass('d-none');
        currentDomain["manual_domain_change"] = true;
    })
    $('#finchat-tab').on('click', function () { 
        $("#chat-pdf-content").addClass('d-none'); 
        $("#chat-content").removeClass('d-none');
        currentDomain["manual_domain_change"] = true;
    })
    $('#assistant-tab').on('shown.bs.tab', function (e) {
        previous_domain = currentDomain["domain"];
        currentDomain["domain"] = "assistant";
        
        if (previous_domain !== currentDomain["domain"] && currentDomain["page_loaded"] && currentDomain["manual_domain_change"]) {
            clearUrlofConversationId();
        }
        currentDomain["page_loaded"] = true;
        
        $("#chat-options-assistant-use-google-scholar").parent().show();
        activateChatTab();
        $(document).trigger('domainChanged');
    });
    $('#search-tab').on('shown.bs.tab', function (e) {
        previous_domain = currentDomain["domain"];
        currentDomain["domain"] = "search";
        
        if (previous_domain !== currentDomain["domain"] && currentDomain["page_loaded"] && currentDomain["manual_domain_change"]) {
            clearUrlofConversationId();
        }
        currentDomain["page_loaded"] = true;
        
        activateChatTab();

        
        
        
        $("#chat-options-assistant-use-google-scholar").parent().show();
        $(document).trigger('domainChanged');
    });

    $('#finchat-tab').on('shown.bs.tab', function (e) {
        previous_domain = currentDomain["domain"];
        currentDomain["domain"] = "finchat";
        
        if (previous_domain !== currentDomain["domain"] && currentDomain["page_loaded"] && currentDomain["manual_domain_change"]) {
            clearUrlofConversationId();
        }
        currentDomain["page_loaded"] = true;
        
        activateChatTab();
        
        // $("#field-selector").val("Finance");
        
        $("#chat-options-assistant-use-google-scholar").parent().hide();
        $(document).trigger('domainChanged');
    });

    // ======== Gear Menu — domain switching + action delegation ========
    $('.gear-domain-item').on('click', function(e) {
        e.preventDefault();
        var newDomain = $(this).data('domain');
        if (newDomain === currentDomain["domain"]) return;

        // Update visual highlight
        $('.gear-domain-item').removeClass('active');
        $(this).addClass('active');

        // Ensure chat content is visible (hide PDF view if open)
        $("#chat-pdf-content").addClass('d-none');
        $("#chat-content").removeClass('d-none');

        // Signal that this is a user-initiated switch (needed for clearUrlofConversationId)
        currentDomain["manual_domain_change"] = true;

        // Switch domain via the hidden tabs — match existing pattern (common-chat.js:834)
        var tabId = { assistant: 'assistant-tab', search: 'search-tab', finchat: 'finchat-tab' };
        $('#pdf-details-tab .nav-link').removeClass('active');
        $('#' + tabId[newDomain]).addClass('active').trigger('shown.bs.tab');
    });

    // Sync gear menu highlight when domain changes from other sources (e.g. conversation load)
    $(document).on('domainChanged', function() {
        $('.gear-domain-item').removeClass('active');
        $('.gear-domain-item[data-domain="' + currentDomain["domain"] + '"]').addClass('active');
    });

    // Action items delegate to existing handlers
    $('#gear-new-temp-chat').on('click', function(e) { e.preventDefault(); $('#new-temp-chat').trigger('click'); });
    $('#gear-aside-chat').on('click', function(e) { e.preventDefault(); openAsideChatModal($('#messageText').val().trim()); });
    $('#gear-get-chat-transcript').on('click', function(e) { e.preventDefault(); $('#get-chat-transcript').trigger('click'); });
    $('#gear-share-chat').on('click', function(e) { e.preventDefault(); $('#share-chat').trigger('click'); });
    $('#gear-conversation-docs').on('click', function(e) { e.preventDefault(); $('#conversation-docs-button').trigger('click'); });
    $('#gear-global-docs').on('click', function(e) { e.preventDefault(); $('#global-docs-button').trigger('click'); });
    $('#gear-logout').on('click', function(e) { e.preventDefault(); $('#logout-link').trigger('click'); });

    // Floating gear menu (compact-nav mode) — same delegation
    $('#gear-floating-show-sidebar').on('click', function(e) { e.preventDefault(); toggleSidebar(); });
    $('#gear-floating-new-temp-chat').on('click', function(e) { e.preventDefault(); $('#new-temp-chat').trigger('click'); });
    $('#gear-floating-aside-chat').on('click', function(e) { e.preventDefault(); openAsideChatModal($('#messageText').val().trim()); });
    $('#gear-floating-transcript').on('click', function(e) { e.preventDefault(); $('#get-chat-transcript').trigger('click'); });
    $('#gear-floating-share').on('click', function(e) { e.preventDefault(); $('#share-chat').trigger('click'); });
    $('#gear-floating-docs').on('click', function(e) { e.preventDefault(); $('#conversation-docs-button').trigger('click'); });
    $('#gear-floating-global-docs').on('click', function(e) { e.preventDefault(); $('#global-docs-button').trigger('click'); });
    $('#gear-floating-logout').on('click', function(e) { e.preventDefault(); $('#logout-link').trigger('click'); });

    // Compact nav toggle — syncs with settings modal checkbox
    $('#gear-compact-nav-toggle, #gear-floating-compact-toggle').on('click', function(e) {
        e.preventDefault();
        e.stopPropagation();
        var isCompact = document.body.classList.contains('compact-nav');
        $('#settings-compact_nav').prop('checked', !isCompact).trigger('change');
    });

    // Compact message card merged menu — populate dynamic state before Bootstrap opens it.
    // Reads word count and current show/hide label from the hidden original elements so the
    // menu always reflects actual card state.
    $(document).on('click', '.compact-message-menu-toggle', function() {
        var $card = $(this).closest('.message-card');
        var $menu = $card.find('.compact-message-dropdown-menu');

        // Word count — only present for assistant messages after initialiseVoteBank runs
        var wcText = $card.find('.vote-dropdown-menu .dropdown-item-text').first().text().trim();
        $menu.find('.compact-word-count').text(wcText).toggle(!!wcText);
        $menu.find('.compact-word-count-divider').toggle(!!wcText);

        // Edit Message — only present for assistant messages
        var hasEdit = $card.find('.vote-dropdown-menu a').filter(function() {
            return $(this).text().trim().indexOf('Edit Message') !== -1;
        }).length > 0;
        $menu.find('.compact-proxy-edit-message').toggle(hasEdit);
        // Hide the divider after edit if neither word count nor edit is present
        $menu.find('.compact-proxy-edit-message').next('.dropdown-divider').toggle(hasEdit || !!wcText);

        // Show/hide toggle — mirror current label ([hide] or [show])
        var hideText = $card.find('.header-hide-toggle').text().trim();
        $menu.find('.compact-proxy-show-hide').html(
            '<i class="bi bi-eye mr-2"></i>' + (hideText || '[show/hide]')
        );

        // Move Pair as Doubt — mirror the original item's visibility (index-based)
        var movePairHidden = $card.find('.move-pair-as-doubt-button').is(':hidden');
        $menu.find('.compact-proxy-move-pair').toggle(!movePairHidden);
    });

    // Proxy handlers — each delegates to the original (hidden) element in the same card.
    $(document).on('click', '.compact-proxy-edit-message', function(e) {
        e.preventDefault();
        $(this).closest('.message-card').find('.vote-dropdown-menu a').filter(function() {
            return $(this).text().trim().indexOf('Edit Message') !== -1;
        }).trigger('click');
    });
    $(document).on('click', '.compact-proxy-bottom', function(e) {
        e.preventDefault();
        $(this).closest('.message-card').find('.scroll-to-bottom-btn').trigger('click');
    });
    $(document).on('click', '.compact-proxy-show-hide', function(e) {
        e.preventDefault();
        $(this).closest('.message-card').find('.header-hide-toggle').trigger('click');
    });
    $(document).on('click', '.compact-proxy-copy', function(e) {
        e.preventDefault();
        $(this).closest('.message-card').find('.copy-btn-header').trigger('click');
    });
    $(document).on('click', '.compact-proxy-show-doubts', function(e) {
        e.preventDefault();
        $(this).closest('.message-card').find('.show-doubts-button').trigger('click');
    });
    $(document).on('click', '.compact-proxy-ask-doubt', function(e) {
        e.preventDefault();
        $(this).closest('.message-card').find('.ask-doubt-button').trigger('click');
    });
    $(document).on('click', '.compact-proxy-fork', function(e) {
        e.preventDefault();
        $(this).closest('.message-card').find('.fork-from-here-button').trigger('click');
    });
    $(document).on('click', '.compact-proxy-delete-message', function(e) {
        e.preventDefault();
        $(this).closest('.message-card').find('.delete-message-button').trigger('click');
    });
    $(document).on('click', '.compact-proxy-delete-pair', function(e) {
        e.preventDefault();
        $(this).closest('.message-card').find('.delete-pair-button').trigger('click');
    });
    $(document).on('click', '.compact-proxy-move-pair', function(e) {
        e.preventDefault();
        $(this).closest('.message-card').find('.move-pair-as-doubt-button').trigger('click');
    });
    // =================================================================

    $('#show-sidebar').on('click', toggleSidebar);
    $('#show-sidebar').on('click', function () { $("#chat-pdf-content").addClass('d-none');});
    $('#chat-area-show-sidebar').on('click', toggleSidebar);
    

    $(document).on('click', '.copy-code-btn', function() {
        copyToClipboard($(this), undefined,  "code");
    });
    hljs.initHighlightingOnLoad();


    function hideNavbar() {
        $('#pdf-details-tab').slideUp();
        $('#hide-navbar').text('Show all');
    }

    function showNavbar() {
        $('#pdf-details-tab').slideDown();
        $('#hide-navbar').text('Show only PDF');
    }



    
    
    $('#documents').on('click', '.list-group-item', function(e) {
        e.preventDefault();
        var docId = $(this).attr('data-doc-id');
        $('.view').empty();
        setActiveDoc(docId);
    });
    $('#pdf-view').show();

    $("#hide-navbar").parent().hide(); // Hide the Show only PDF button

    // Listen for click events on the tabs
    $(".nav-link").click(function() {
        // Check if the PDF tab is active
        pdfTabIsActive();
    });

    active_tab = "assistant-tab" // search-tab finchat-tab assistant-tab

    $("a#search-tab.nav-link").removeClass('active');
    $("a#pdf-tab.nav-link").removeClass('active');
    $("a#search-tab").removeClass('active');
    $('#' + active_tab).trigger('shown.bs.tab');
    $('a#' + active_tab).addClass('active');
    // $("input[name='chat-options-assistant-provide-detailed-answers-checkboxOptions'][value='4']").prop("checked", true);
    
    
    pdfTabIsActive();
    // $("#assistant-tab").tigger('click');
    // $("a#assistant-tab.nav-link").trigger('click');

}

