$(document).ready(function() {
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
    })
    $('#search-tab').on('click', function () { 
        $("#chat-pdf-content").addClass('d-none'); 
        $("#chat-content").removeClass('d-none');
    })
    $('#finchat-tab').on('click', function () { 
        $("#chat-pdf-content").addClass('d-none'); 
        $("#chat-content").removeClass('d-none');
    })
    $('#assistant-tab').on('shown.bs.tab', function (e) {
        currentDomain["domain"] = "assistant";
        $("#field-selector").val("None");
        $('#permanentText').show();
        $('#linkInput').show();
        $('#searchInput').show();
        $("#field-selector").parent().show();
        $("#chat-options-assistant-use-google-scholar").parent().show();
        $("#chat-options-assistant-use-multiple-docs-checkbox").parent().hide();
        $("#chat-options-assistant-tell-me-more-checkbox").parent().show();
        activateChatTab();
    });
    $('#search-tab').on('shown.bs.tab', function (e) {
        currentDomain["domain"] = "search";
        $("#field-selector").val("None");
        activateChatTab();
        $('#permanentText').hide();
        $('#linkInput').hide();
        $('#searchInput').hide();
        
        $("#field-selector").parent().show();
        $("#chat-options-assistant-use-google-scholar").parent().show();
        $("#chat-options-assistant-use-multiple-docs-checkbox").parent().hide();
        $("#chat-options-assistant-tell-me-more-checkbox").parent().show();
    });

    $('#finchat-tab').on('shown.bs.tab', function (e) {
        currentDomain["domain"] = "finchat";
        activateChatTab();
        $('#linkInput').hide();
        $('#searchInput').hide();
        $('#permanentText').hide();
        $("#field-selector").val("Finance");
        $("#field-selector").parent().hide();
        $("#chat-options-assistant-use-google-scholar").parent().hide();
        $("#chat-options-assistant-use-google-scholar").prop('checked', false);
        $("#chat-options-assistant-use-multiple-docs-checkbox").parent().hide();
        $("#chat-options-assistant-use-multiple-docs-checkbox").prop('checked', false);
        $("#chat-options-assistant-tell-me-more-checkbox").parent().hide();
        $("#chat-options-assistant-tell-me-more-checkbox").prop('checked', false);
        
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



    function initiliseNavbarHiding() {
        var viewer = document.getElementById('pdfjs-viewer');
        function resizePdfView(event) {
            var width = $('#content-col').width();
            var height = $("#pdf-questions").is(':hidden')? $(window).height()-10 :$(window).height() * 0.8;
            $('#pdf-content').css({
                'width': width,
                'height': height,
            });
            $(viewer).css({
                'width': '100%',
                'height': height-10,
            });
        }

        var escKeyUp = function(e) {
            // keyCode for Escape key is 27
            if (e.keyCode == 27) {
                clearTimeout(hideTimeout);
                // Show navbar if it is currently hidden
                if($('#hide-navbar').text() === 'Show all') {
                    toggleView();
                }
            }
        }
        $(window).keyup(escKeyUp);
        function toggleView() {
            if ($(this).text() === 'Show only PDF') {
                hideNavbar();
                toggleSidebar();
                $("#pdf-questions").hide();
                $(window).resize(resizePdfView).trigger('resize');
                $(window).keyup(escKeyUp);
            } else {
                showNavbar();
                toggleSidebar();
                $("#pdf-questions").show();
                $(window).resize(resizePdfView).trigger('resize');
            }
        }
        

        $('#hide-navbar').on('click', toggleView);
    
        var hideTimeout;
    
        $('#navbar-trigger').mouseenter(function() {
            // Cancel hiding if it was scheduled
            clearTimeout(hideTimeout);
            
            // Show all if it is currently hidden
            if($('#hide-navbar').text() === 'Show all') {
                $('#pdf-details-tab').slideDown();
            }
        });
    
        $('#navbar-trigger').mouseleave(function() {
            // Schedule hiding after a delay if navbar is currently shown
            if($('#hide-navbar').text() === 'Show all') {
                hideTimeout = setTimeout(function() {
                    $('#pdf-details-tab').slideUp();
                }, 700);  // delay in ms
            }
        });
    
        $('#pdf-details-tab').mouseenter(function() {
            // Cancel hiding if it was scheduled
            clearTimeout(hideTimeout);
        });
    
        $('#pdf-details-tab').mouseleave(function() {
            // Schedule hiding after a delay if navbar is currently shown
            if($('#hide-navbar').text() === 'Show all') {
                hideTimeout = setTimeout(function() {
                    $('#pdf-details-tab').slideUp();
                }, 700);  // delay in ms
            }
        });
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

    $('#search-tab').trigger('shown.bs.tab');
    $("a#search-tab.nav-link").addClass('active');
    $("a#pdf-tab.nav-link").removeClass('active');
    pdfTabIsActive();
    // $("#assistant-tab").tigger('click');
    // $("a#assistant-tab.nav-link").trigger('click');

});
