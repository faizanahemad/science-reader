var ConversationManager = {
    activeConversationId: null,
  
    listConversations: function() {
      // The code to list conversations goes here...
    },
  
    createConversation: function() {
        $.ajax({
            url: '/create_conversation',
            type: 'POST',
            success: function(conversation) {
                // Add new conversation to the list
                loadConversations(false).done(function(){
                    // Set the new conversation as the active conversation and highlight it
                    ConversationManager.setActiveConversation(conversation.conversation_id);
                    highLightActiveConversation();
                });
            }
        });
    },
  
    deleteConversation: function(conversationId) {
        $.ajax({
            url: '/delete_conversation/' + conversationId,
            type: 'DELETE',
            success: function(result) {
                // Remove the conversation from the sidebar
                $("a[data-conversation-id='" + conversationId + "']").remove();
                // If the deleted conversation is the active conversation
                if(ConversationManager.activeConversationId == conversationId){
                    // Set the first conversation as the active conversation
                    var firstConversationId = $('#conversations a:first').attr('data-conversation-id');
                    // TODO: if there are no conversations, then hide the chat view
                    ConversationManager.setActiveConversation(firstConversationId);
                    highLightActiveConversation();
                }
            }
        });
    },
  
    setActiveConversation: function(conversationId) {
        this.activeConversationId = conversationId;
        // Load and render the messages in the active conversation, clear chat view
        ChatManager.listMessages(conversationId).done(function(messages) {
            ChatManager.renderMessages(messages, true);
        });
    }

};

function renderStreamingResponse(streamingResponse, conversationId, messageText) {
    var reader = streamingResponse.body.getReader();
    var decoder = new TextDecoder();
    let card = null;
    let answerParagraph = null;
    var content_length = 0;
    var answer = ''

    async function read() {
        const {value, done} = await reader.read();

        if (done) {
            resetOptions('chat-options', 'assistant');
            console.log('Stream complete');
            // Final rendering of markdown and setting up the voting mechanism
            if (answerParagraph) {
                renderInnerContentAsMarkdown(answerParagraph, function(){
                    showMore(null, text=null, textElem=answerParagraph, as_html=true, show_at_start=true);
                });
                initialiseVoteBank(card, messageText, activeDocId=ConversationManager.activeConversationId);
            }
            return;
        }

        let part = decoder.decode(value).replace(/\n/g, '<br>');
        answer = answer + part;

        // Render server message
        var serverMessage = {
            sender: 'server',
            text: part
        };

        if (!card) {
            card = ChatManager.renderMessages([serverMessage], false);
        }  
        if (!answerParagraph) {
            answerParagraph = card.find('.card-body p').last();
        }
        answerParagraph.append(part);  // Find the last p tag within the card-body and append the message part
        if (answerParagraph.html().length > content_length + 40){
            renderInnerContentAsMarkdown(answerParagraph, 
                                            callback=null, continuous=true)
            content_length = answerParagraph.html().length
        }

        // Recursive call to read next message part
        setTimeout(read, 0);
    }

    read();
}


function highLightActiveConversation(){
    $('#conversations .list-group-item').removeClass('active');
    $('#conversations .list-group-item[data-conversation-id="' + ConversationManager.activeConversationId + '"]').addClass('active');
}

var ChatManager = {
    listMessages: function(conversationId) {
      return $.ajax({
          url: '/list_messages_by_conversation/' + conversationId,
          type: 'GET'
      });
    },
    deleteLastMessage: function(conversationId) {
        return $.ajax({
            url: '/delete_last_message/' + conversationId,
            type: 'DELETE',
            success: function(response) {
                // Reload the conversation
                ChatManager.listMessages(conversationId).done(function(messages) {
                    ChatManager.renderMessages(messages);
                });
            }
        });
    },
  
    renderMessages: function(messages, shouldClearChatView) {
        if (shouldClearChatView) {
            $('#chatView').empty();  // Clear the chat view first
        }
        messages.forEach(function(message, index, array) {
            var senderText = message.sender === 'user' ? 'You' : 'Assistant';
            var messageElement = $('<div class="card w-75 my-2 d-flex flex-column"></div>');
            
            var cardHeader = $('<div class="card-header text-end"><strong>' + senderText + '</strong></div>');
            var cardBody = $('<div class="card-body"></div>');
            var textElem = $('<p class="card-text">' + message.text.replace(/\n/g, '<br>') + '</p>');
            
            cardBody.append(textElem);
            messageElement.append(cardHeader);
            messageElement.append(cardBody);
            
            // Depending on who the sender is, we adjust the alignment and add different background shading
            if (message.sender == 'user') {
                messageElement.addClass('ml-md-auto');  // For right alignment
                messageElement.css('background-color', '#faf5ff');  // Lighter shade of purple
            } else {
                initialiseVoteBank(messageElement, message.text, contentId=message.message_id, activeDocId=ConversationManager.activeConversationId);
                messageElement.addClass('mr-md-auto');  // For left alignment
                messageElement.css('background-color', '#f5fcff');  // Lighter shade of blue
            }
            renderInnerContentAsMarkdown(textElem, function(){
                showMore(null, text=null, textElem=textElem, as_html=true, show_at_start=index >= array.length - 2);
            });
            
            $('#chatView').append(messageElement);
        });
        var chatView = $('#chatView');
        chatView.scrollTop(chatView.prop('scrollHeight'));
        return $('#chatView').find('.card').last();
    },



  
    sendMessage: function(conversationId, messageText, checkboxes, links, search) {
        // Render user's message immediately
        var userMessage = {
            sender: 'user',
            text: messageText
        };
        ChatManager.renderMessages([userMessage], false);

        // Use Fetch API to make request
        return fetch('/send_message/' + conversationId, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                'messageText': messageText,
                'permanentMessageText': $('#permanentMessageText').val(),
                'checkboxes': checkboxes,
                'links': links,
                'search': search
            })
        });
    }

};


function loadConversations(autoselect=true) {
    var api = '/list_conversation_by_user';
    var request = apiCall(api, 'GET', {})

    request.done(function(data) {
        // Auto-select the first conversation
        var firstConversation = true;
        $('#conversations').empty();

        // Since we want most recently updated conversations at the top, reverse the data
        data.reverse().forEach(function(conversation) {
            var conversationItem = $('<a href="#" class="list-group-item list-group-item-action" data-conversation-id="' + conversation.conversation_id + '"></a>');
            var deleteButton = $('<small><button class="btn p-0 ms-2 delete-chat-button"><i class="bi bi-trash-fill"></i></button></small>');

            conversationItem.append('<strong class="conversation-title-in-sidebar">' + conversation.title.slice(0, 60).trim() + '</strong></br>');
            conversationItem.append(deleteButton);

            // Add a button for conversation details
            var detailButton = $('<small><button class="btn p-0 ms-2 detail-button"><i class="bi bi-info-circle-fill"></i></button></small>');
            conversationItem.append(detailButton);
            
            // Include a summary of the conversation
            showMore(conversationItem, conversation.summary_till_now);
            
            $('#conversations').append(conversationItem);
            conversationItem.on('click', function() {
                var conversationId = $(this).attr('data-conversation-id');
                ConversationManager.setActiveConversation(conversationId);
                highLightActiveConversation();
            });

            if (autoselect){
                if (firstConversation) {
                    ConversationManager.setActiveConversation(conversation.conversation_id);
                    highLightActiveConversation();
                    firstConversation = false;
                }
            }
        });
        if (data.length === 0) {
            ConversationManager.createConversation();
        }

        // Handle click events for the delete button
        $('.delete-chat-button').click(function(event) {
            event.preventDefault();
            event.stopPropagation();
            var conversationId = $(this).closest('[data-conversation-id]').attr('data-conversation-id');
            ConversationManager.deleteConversation(conversationId);
        });

        // Handle click events for the detail button
        $('.detail-button').click(function(event) {
            event.preventDefault();
            event.stopPropagation();
            var conversationId = $(this).closest('[data-conversation-id]').attr('data-conversation-id');
            // TODO: show the conversation details
        });
    });

    return request;
}

function sendMessageCallback() {
    var messageText = $('#messageText').val();
    $('#messageText').val('');  // Clear the messageText field
    var checkboxes = {
        'webSearch': $('#webSearchCheckbox').is(':checked'),
        'document': $('#documentCheckbox').is(':checked'),
        'googleScholar': $('#googleScholarCheckbox').is(':checked'),
        'longerResponses': $('#longerResponses').is(':checked'),
    };
    var links = $('#linkInput').val().split('\n');
    var search = $('#searchInput').val().split('\n');
    let options = getOptions('chat-options', 'assistant');

    ChatManager.sendMessage(ConversationManager.activeConversationId, messageText, options, links, search).then(function(response) {
        if (!response.ok) {
            alert('An error occurred: ' + response.status);
            return;
        }
        // Call the renderStreamingResponse function to handle the streaming response
        renderStreamingResponse(response, ConversationManager.activeConversationId, messageText);
    });
}

$(document).ready(function() {
    $('#chat-assistant-view').hide();
    loadConversations();
    
    $('#add-new-chat').on('click', function() {
        ConversationManager.createConversation();
    });
    $('#sendMessageButton').on('click', sendMessageCallback);
    $('#messageText').keypress(function(e) { // Add this block to submit the question on enter
            if (e.which == 13) {
                sendMessageCallback();
                return false; // Prevents the default action
            }
        });

    $('#deleteLastTurn').click(function() {
        if (ConversationManager.activeConversationId) {
            ChatManager.deleteLastMessage(ConversationManager.activeConversationId);
        }
    });
    addOptions('chat-options', 'assistant');

})
