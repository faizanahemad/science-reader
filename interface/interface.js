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
            // scroll to the top of the page
            $(document).scrollTop(0);
            // scroll to the top of the page for the window
            $(window).scrollTop(0);
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
            $('#logout-link').attr('href', '/logout');
        });
    }
    


    
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
        $("#field-selector").val("None");
        $('#permanentText').show();
        $('#linkInput').show();
        $('#searchInput').show();
        $("#field-selector").parent().show();
        $("#preamble-selector").val("").val(["Wife Prompt"]);
        $("#chat-options-assistant-use-google-scholar").parent().show();
        $("#chat-options-assistant-use-multiple-docs-checkbox").parent().hide();
        $("#chat-options-assistant-tell-me-more-checkbox").parent().show();
        $("#user-preferences-modal-open-button").parent().show();
        $("#user-details-modal-open-button").parent().show();
        activateChatTab();
    });
    $('#search-tab').on('shown.bs.tab', function (e) {
        previous_domain = currentDomain["domain"];
        currentDomain["domain"] = "search";
        
        if (previous_domain !== currentDomain["domain"] && currentDomain["page_loaded"] && currentDomain["manual_domain_change"]) {
            clearUrlofConversationId();
        }
        currentDomain["page_loaded"] = true;
        $("#field-selector").val("None");
        activateChatTab();
        $('#permanentText').hide();
        $('#linkInput').hide();
        $('#searchInput').hide();

        $("#preamble-selector").val("").val(["Wife Prompt"]);
        
        $("#field-selector").parent().show();
        $("#chat-options-assistant-use-google-scholar").parent().show();
        $("#chat-options-assistant-use-multiple-docs-checkbox").parent().hide();
        // $("#chat-options-assistant-tell-me-more-checkbox").parent().show();
        $("#chat-options-assistant-tell-me-more-checkbox").parent().hide();
        $("#chat-options-assistant-tell-me-more-checkbox").prop('checked', false);

        $("input[name='chat-options-assistant-provide-detailed-answers-checkboxOptions'][value='2']").prop("checked", true);
        $("input[name='chat-options-assistant-provide-detailed-answers-checkboxOptions'][value='4']").prop("checked", false);
        $("#user-preferences-modal-open-button").parent().show();
        $("#user-details-modal-open-button").parent().show();

        

        $("#chat-options-assistant-ensemble").parent().hide();
        $("#chat-options-assistant-ensemble").prop('checked', false);
    });

    $('#finchat-tab').on('shown.bs.tab', function (e) {
        previous_domain = currentDomain["domain"];
        currentDomain["domain"] = "finchat";
        
        if (previous_domain !== currentDomain["domain"] && currentDomain["page_loaded"] && currentDomain["manual_domain_change"]) {
            clearUrlofConversationId();
        }
        currentDomain["page_loaded"] = true;
        
        activateChatTab();
        $('#linkInput').hide();
        $('#searchInput').hide();
        $('#permanentText').hide();
        // $("#field-selector").val("Finance");
        $("#field-selector").val("None");
        $("#preamble-selector").val("").val(["Short Coding Interview"]);
        $("#field-selector").parent().show();
        $("input[name='chat-options-assistant-provide-detailed-answers-checkboxOptions'][value='2']").prop("checked", true);
        $("input[name='chat-options-assistant-provide-detailed-answers-checkboxOptions'][value='4']").prop("checked", false);

        $("#chat-options-assistant-use-google-scholar").parent().hide();
        $("#chat-options-assistant-use-google-scholar").prop('checked', false);
        $("#chat-options-assistant-use-multiple-docs-checkbox").parent().hide();
        $("#chat-options-assistant-use-multiple-docs-checkbox").prop('checked', false);
        $("#chat-options-assistant-tell-me-more-checkbox").parent().hide();
        $("#chat-options-assistant-tell-me-more-checkbox").prop('checked', false);

        $("#chat-options-assistant-search-exact").parent().hide();
        $("#chat-options-assistant-search-exact").prop('checked', false);

        $("#chat-options-assistant-ensemble").parent().hide();
        $("#chat-options-assistant-ensemble").prop('checked', false);
        $("#user-preferences-modal-open-button").parent().hide();
        $("#user-details-modal-open-button").parent().hide();
        // $('#toggleChatControls').click();
        
    });
    
    $('#show-sidebar').on('click', toggleSidebar);
    $('#show-sidebar').on('click', function () { $("#chat-pdf-content").addClass('d-none');});
    

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

    active_tab = "finchat-tab" // search-tab finchat-tab assistant-tab

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

