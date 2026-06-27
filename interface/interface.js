var userDetails = {
    email: null,
    name: null
}

// ===== Reading Overlay =====
// Opens a full-viewport reading view for an assistant answer card.
// Accepts a jQuery element that is the card itself or any descendant of it.
// Supported card wrappers: .message-card, .doubt-conversation-card, .temp-llm-card
window.openReadingOverlay = function($triggerElem) {
    var $overlay = $('#reading-overlay');
    var $body = $('#reading-overlay-body');

    var contentHtml = '';

    var $mainCard = $triggerElem.closest('.message-card');
    var $doubtCard = $triggerElem.closest('.doubt-conversation-card');
    var $tempCard = $triggerElem.closest('.temp-llm-card');

    if ($mainCard.length) {
        // After streaming, all content (including .more-text) lives in the sibling
        // #message-render-space-md-render — NOT inside .actual-card-text which is
        // hidden and empty. For server-loaded answers, .more-text lives inside
        // .actual-card-text. We check both locations.
        var $moreText = $mainCard.find('.actual-card-text .more-text').first();
        if (!$moreText.length) {
            // Streaming case: showMore() wraps content inside #message-render-space-md-render
            $moreText = $mainCard.find('#message-render-space-md-render .more-text').first();
        }
        if ($moreText.length) {
            contentHtml = $moreText.html();
        } else {
            // No showMore wrapping (short card) — try .actual-card-text content directly
            contentHtml = $mainCard.find('.actual-card-text').first().html();
            if (!contentHtml) {
                // Short streaming card: content is directly in #message-render-space-md-render
                contentHtml = $mainCard.find('#message-render-space-md-render').first().html();
            }
        }
    } else if ($doubtCard.length) {
        contentHtml = $doubtCard.find('.card-body').first().html();
    } else if ($tempCard.length) {
        contentHtml = $tempCard.find('.card-body').first().html();
    }

    if (!contentHtml) return;

    $body.html(contentHtml);
    $overlay.show();
    $('body').addClass('reading-overlay-open');
    $overlay[0].scrollTop = 0;
};

window.closeReadingOverlay = function() {
    $('#reading-overlay').hide();
    $('#reading-overlay-body').empty();
    $('body').removeClass('reading-overlay-open');
};
// ===== /Reading Overlay =====

function interface_readiness() {
    const options = {
        throwOnError: false,
        trust: true
    };
    
    var activeDocId = localStorage.getItem('activeDocId') || null;
    var pdfUrl = null;
    
    
    
    
    

    function toggleSidebar() {
        var sidebar = $('#chat-assistant-sidebar');
        var contentCol = $('#chat-assistant');
        if (!sidebar.length) return;

        // Use an explicit state flag rather than :visible, which can give
        // misleading results on mobile (col-12 stacked layout with sticky-top
        // keeps the sidebar "visible" even when it fills the viewport).
        var isHidden = sidebar.hasClass('d-none');

        if (isHidden) {
            // Show sidebar
            sidebar.removeClass('d-none');
            contentCol.removeClass('col-md-12').addClass('col-md-9');
        } else {
            // Hide sidebar
            sidebar.addClass('d-none');
            contentCol.removeClass('col-md-9').addClass('col-md-12');
        }

        // Trigger the resize event to adjust the size of the PDF viewer
        $(window).trigger('resize');
    }

    
    
    function showUserName(){
        // Item 3.4: return the jqXHR promise for potential future chaining.
        return $.get('/get_user_info', function(data) {
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
    $('#gear-new-chat').on('click', function(e) { e.preventDefault(); $('#add-new-chat').trigger('click'); });
    $('#gear-new-temp-chat').on('click', function(e) { e.preventDefault(); $('#new-temp-chat').trigger('click'); });
    $('#gear-aside-chat').on('click', function(e) { e.preventDefault(); openAsideChatModal($('#messageText').val().trim()); });
    $('#gear-get-chat-transcript').on('click', function(e) { e.preventDefault(); $('#get-chat-transcript').trigger('click'); });
    $('#gear-share-chat').on('click', function(e) { e.preventDefault(); $('#share-chat').trigger('click'); });
    $('#gear-starred-messages').on('click', function(e) { e.preventDefault(); $('#starred-messages-btn').trigger('click'); });
    $('#gear-conversation-docs').on('click', function(e) { e.preventDefault(); $('#conversation-docs-button').trigger('click'); });
    $('#gear-global-docs').on('click', function(e) { e.preventDefault(); $('#global-docs-button').trigger('click'); });
    $('#gear-logout').on('click', function(e) { e.preventDefault(); $('#logout-link').trigger('click'); });

    // Floating gear menu (compact-nav mode) — same delegation
    $('#gear-floating-show-sidebar').on('click', function(e) { e.preventDefault(); toggleSidebar(); });
    $('#gear-floating-new-chat').on('click', function(e) { e.preventDefault(); $('#add-new-chat').trigger('click'); });
    $('#gear-floating-new-temp-chat').on('click', function(e) { e.preventDefault(); $('#new-temp-chat').trigger('click'); });
    $('#gear-floating-aside-chat').on('click', function(e) { e.preventDefault(); openAsideChatModal($('#messageText').val().trim()); });
    $('#gear-floating-transcript').on('click', function(e) { e.preventDefault(); $('#get-chat-transcript').trigger('click'); });
    $('#gear-floating-share').on('click', function(e) { e.preventDefault(); $('#share-chat').trigger('click'); });
    $('#gear-floating-starred').on('click', function(e) { e.preventDefault(); $('#starred-messages-btn').trigger('click'); });
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
    // Reads live card state (word count, show/hide label, inline display styles) so items
    // are only visible when their underlying action is actually available for that card.
    $(document).on('click', '.compact-message-menu-toggle', function() {
        var $card = $(this).closest('.message-card');
        var $menu = $card.find('.compact-message-dropdown-menu');

        // Word count — computed directly from rendered card text so it is immune to
        // Bootstrap event ordering (the hidden vote-dropdown-menu is read after Bootstrap
        // opens the dropdown, which can cause the first render to show stale content).
        var $cardText = $card.find('.actual-card-text').first();
        var rawWcText = $cardText.text().trim();
        var wordCountNum = rawWcText ? rawWcText.split(/\s+/).filter(Boolean).length : 0;
        var wcText = wordCountNum > 0 ? wordCountNum.toLocaleString() + ' words' : '';
        $menu.find('.compact-word-count').text(wcText).toggle(!!wcText);
        $menu.find('.compact-word-count-divider').toggle(!!wcText);

        // Edit Message — present for all cards after initialiseVoteBank runs
        var hasEdit = $card.find('.vote-dropdown-menu a').filter(function() {
            return $(this).text().trim().indexOf('Edit Message') !== -1;
        }).length > 0;
        $menu.find('.compact-proxy-edit-message').toggle(hasEdit);
        // Divider below edit section only when Edit Message itself is shown (S2-B: was hasEdit||!!wcText)
        $menu.find('.compact-proxy-edit-message').next('.dropdown-divider').toggle(hasEdit);

        // Bottom — only active when decorateMessageCardNav has shown the button.
        // Check the inline style directly (not computed) so body.compact-nav !important
        // hiding the element does not give a false negative.
        var $bottomBtn = $card.find('.scroll-to-bottom-btn').first();
        var bottomActive = $bottomBtn.length > 0 && $bottomBtn[0].style.display !== 'none';
        $menu.find('.compact-proxy-bottom').toggle(bottomActive);

        // Show/hide toggle — only active when decorateMessageCardNav has revealed the link.
        // Same inline-style check: template starts it at display:none; decorateMessageCardNav
        // calls .show() which clears that inline value (style.display === '').
        var $hideToggle = $card.find('.header-hide-toggle').first();
        var hideActive = $hideToggle.length > 0 && $hideToggle[0].style.display !== 'none';
        $menu.find('.compact-proxy-show-hide').toggle(hideActive);
        if (hideActive) {
            $menu.find('.compact-proxy-show-hide').html(
                '<i class="bi bi-eye mr-2"></i>' + ($hideToggle.text().trim() || '[show/hide]')
            );
        }

        // Move Pair as Doubt — mirror the original item's index-based visibility
        var movePairHidden = $card.find('.move-pair-as-doubt-button').is(':hidden');
        $menu.find('.compact-proxy-move-pair').toggle(!movePairHidden);

        // Read Full Screen — always visible; no underlying element to proxy
        // (compact-proxy-read divider is always shown alongside it)
        $menu.find('.compact-read-divider').show();
        $menu.find('.compact-proxy-read').show();
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
    $(document).on('click', '.compact-proxy-read', function(e) {
        e.preventDefault();
        window.openReadingOverlay($(this).closest('.message-card'));
    });

    // Reading overlay — close button and Escape key
    $(document).on('click', '#reading-overlay-close', function() {
        window.closeReadingOverlay();
    });
    $(document).on('keydown.readingOverlay', function(e) {
        if (e.key === 'Escape' && $('#reading-overlay').is(':visible')) {
            window.closeReadingOverlay();
        }
    });
    // =================================================================

    $('#show-sidebar').on('click', toggleSidebar);
    $('#show-sidebar').on('click', function () { $("#chat-pdf-content").addClass('d-none');});
    $('#chat-area-show-sidebar').on('click', toggleSidebar);
    $('#sidebar-close-btn').on('click', toggleSidebar);
    

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

