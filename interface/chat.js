$(document).ready(function() {
    
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
        if (e.which == 13 && !e.shiftKey && !e.altKey) {
            if (this.id == 'messageText'){
                sendMessageCallback();
            }
            else {
                addNewlineToTextbox(this_id);
            }
            return false; // Prevents the default action
        }
        if ((e.keyCode == 13 && e.altKey) || (e.keyCode == 13 && e.shiftKey)) {
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
})

