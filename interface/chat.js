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
        if ((e.which != 13) && (e.which != 8) && (e.which != 46) && (e.which != 37) && (e.which != 38) && (e.which != 39) && (e.which != 40)) {
            var scrollHeight = $(this).prop('scrollHeight');
            var maxHeight = parseFloat($(this).css('max-height'));
            if(scrollHeight > maxHeight) {
                $(this).scrollTop(scrollHeight);
            }
        }
    }
    $('#messageText').keypress(textboxCallBack);
    $('#messageText').on('input change', textboxCallBack);
    addOptions('chat-options', 'assistant', null);
    $('#sendMessageButton').on('click', sendMessageCallback);
    $('.dynamic-textarea').on('input change', function() {
      if ($(this).val().length === 0) {
          // If the textarea is empty, reset to the default height of 30px
          this.style.height = '35px';
      } else {
        
          this.style.height = 'auto'; // Reset height to auto to recalculate
          this.style.height = (this.scrollHeight) + 'px'; // Set the new height based on content
      }
    });
    $('#toggleChatControls').click(function () {
        $('#chat-search-links-input').toggleClass('d-none');
        $('#chat-options').toggleClass('d-none');
        // ▲ ▼
        // change inner content of the button based on current content
        var currentContent = $(this).text();
        var newContent = currentContent === '▲' ? '▼' : '▲';
        $(this).text(newContent);
    });

    $('#toggleChatDocsView').click(function () {
        $('#chat-doc-view').toggleClass('d-none');
        // ▲ ▼
        // change inner content of the button based on current content
        var currentContent = $(this).text();
        var newContent = currentContent === '▲' ? '▼' : '▲';
        $(this).text(newContent);
    });
    $(window).scrollTop(0);
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
    
}

$(document).ready(function() {
    chat_interface_readiness();
    interface_readiness();
});

