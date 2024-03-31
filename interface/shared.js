function loadSharedConversation(conversationId) {
    var api = '/shared_chat/' + conversationId;
    var request = apiCall(api, 'GET', {})

    request.done(function (data) {
        $('#conversations').empty();

        // detect class removal from above element

        function hidePDF() {
            $("#chat-pdf-content").addClass('d-none');
            $('#chat-content').removeClass('d-none');
        }
        $('#assistant-tab').on('click', function () { 
            hidePDF();
        })

        // Since we want most recently updated conversations at the top, reverse the data
        conversation = data.metadata
        conversationId = conversation.conversation_id
        var conversationItem = $('<a href="#" class="list-group-item list-group-item-action" data-conversation-id="' + conversation.conversation_id + '"></a>');
        conversationItem.append('<strong class="conversation-title-in-sidebar">' + conversation.title.slice(0, 60).trim() + '</strong></br>');
        showMore(conversationItem, conversation.summary_till_now, textElem = null, as_html = false, show_at_start = false);
        // showMore(conversationItem, text=null, textElem=$('#summary-text'), as_html=true);
        $('#conversations').append(conversationItem);
        ChatManager.renderMessages(conversationId, data.messages, true, false);
        ChatManager.renderDocuments(conversationId, data.documents);
        ChatManager.setupDownloadChatButton(conversationId);
        ChatManager.setupShareChatButton(conversationId);
        highLightActiveConversation(conversationId);
        var chatView = $('#chatView');
        chatView.scrollTop(chatView.prop('scrollHeight'));
        setTimeout(function () {
            chatView.scrollTop(chatView.prop('scrollHeight'));
        }, 150);
    });
}

$(document).ready(function () {
    hljs.initHighlightingOnLoad();
    $(document).on('click', '.copy-code-btn', function () {
        copyToClipboard($(this), undefined, "code");
    });
    // <div id="{conversation_id}" data-conversation_id="{conversation_id}" style="display: none;"></div>
    conversation_id = $('#conversation_id').data('conversation_id');
    loadSharedConversation(conversation_id);
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
    $("#chat-pdf-content").addClass('d-none');
});