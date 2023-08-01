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
                loadConversations(true).done(function(){
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

function renderStreamingResponseT(streamingResponse, conversationId, messageText) {
    var reader = streamingResponse.body.getReader();
    var decoder = new TextDecoder();
    let card = null;
    let answerParagraph = null;
    var content_length = 0;
    var answer = ''

    async function read() {
        const {value, done} = await reader.read();
        if (done) {
            $('#messageText').prop('disabled', false);
            var statusDiv = card.find('.status-div');
            statusDiv.hide();
            statusDiv.find('.status-text').text('');
            statusDiv.find('.spinner-border').hide();
            statusDiv.find('.spinner-border').removeClass('spinner-border');
            // resetOptions('chat-options', 'assistant');
            console.log('Stream complete');
            // Final rendering of markdown and setting up the voting mechanism
            if (answerParagraph) {
                renderInnerContentAsMarkdown(answerParagraph, function(){
                    if (answerParagraph.text().length > 300) {
                        showMore(null, text=null, textElem=answerParagraph, as_html=true, show_at_start=true);
                    }
                });
                initialiseVoteBank(card, `${messageText} + '\n\n' + ${answer}`, contentId=null, activeDocId=ConversationManager.activeConversationId);
            }
            return;
        }

        let part = decoder.decode(value)
        part = JSON.parse(part);
        part['text'] = part['text'].replace(/\n/g, '  \n');

        answer = answer + part['text'];

        // Render server message
        var serverMessage = {
            sender: 'server',
            text: ''
        };

        if (!card) {
            card = ChatManager.renderMessages([serverMessage], false);
        }  
        if (!answerParagraph) {
            answerParagraph = card.find('.actual-card-text').last();
        }
        var statusDiv = card.find('.status-div');
        statusDiv.show();
        statusDiv.find('.spinner-border').show();
        answerParagraph.append(part['text']);  // Find the last p tag within the card-body and append the message part
        answer_pre_text = answerParagraph.text()
        if (answerParagraph.html().length > content_length + 40){
            renderInnerContentAsMarkdown(answerParagraph, 
                                            callback=null, continuous=true)
            content_length = answerParagraph.html().length
        }
        answer_post_text = answerParagraph.text()
        var statusDiv = card.find('.status-div');
        statusDiv.find('.status-text').text(part['status']);

        // Recursive call to read next message part
        setTimeout(read, 10);
    }

    read();
}

function renderStreamingResponse(streamingResponse, conversationId, messageText) {
    var reader = streamingResponse.body.getReader();
    var decoder = new TextDecoder();
    let buffer = '';
    let card = null;
    let answerParagraph = null;
    var content_length = 0;
    var answer = ''

    async function read() {
        const {value, done} = await reader.read();

        buffer += decoder.decode(value || new Uint8Array, {stream: !done});
        let boundary = buffer.indexOf('\n');
        // Render server message
        var serverMessage = {
            sender: 'server',
            text: ''
        };

        if (!card) {
            card = ChatManager.renderMessages([serverMessage], false);
        }
        while (boundary !== -1) {
            const part = JSON.parse(buffer.slice(0, boundary));
            buffer = buffer.slice(boundary + 1);
            boundary = buffer.indexOf('\n');

            part['text'] = part['text'].replace(/\n/g, '  \n');
            answer = answer + part['text'];

              
            if (!answerParagraph) {
                answerParagraph = card.find('.actual-card-text').last();
            }
            var statusDiv = card.find('.status-div');
            statusDiv.show();
            statusDiv.find('.spinner-border').show();
            answerParagraph.append(part['text']);  // Find the last p tag within the card-body and append the message part
            answer_pre_text = answerParagraph.text()
            if (answerParagraph.html().length > content_length + 40){
                renderInnerContentAsMarkdown(answerParagraph, 
                                                callback=null, continuous=true)
                content_length = answerParagraph.html().length
            }
            answer_post_text = answerParagraph.text()
            var statusDiv = card.find('.status-div');
            statusDiv.find('.status-text').text(part['status']);
        }

        if (done) {
            $('#messageText').prop('disabled', false);
            var statusDiv = card.find('.status-div');
            statusDiv.hide();
            statusDiv.find('.status-text').text('');
            statusDiv.find('.spinner-border').hide();
            statusDiv.find('.spinner-border').removeClass('spinner-border');
            resetOptions('chat-options', 'assistant');
            console.log('Stream complete');
            // Final rendering of markdown and setting up the voting mechanism
            if (answerParagraph) {
                renderInnerContentAsMarkdown(answerParagraph, function(){
                    if (answerParagraph.text().length > 300) {
                        showMore(null, text=null, textElem=answerParagraph, as_html=true, show_at_start=true);
                    }
                });
                initialiseVoteBank(card, `${messageText} + '\n\n' + ${answer}`, contentId=null, activeDocId=ConversationManager.activeConversationId);
            }
            return;
        }
        // Recursive call to read next message part
        setTimeout(read, 10);
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
          var messageElement = $('<div class="card w-75 my-2 d-flex flex-column" style="width: 80%!important;"></div>');
          
          var cardHeader = $('<div class="card-header text-end"><strong>' + senderText + '</strong></div>');
          var cardBody = $('<div class="card-body chat-card-body"></div>');
          var textElem = $('<p id="message-render-space" class="card-text actual-card-text">' + message.text.replace(/\n/g, '  \n') + '</p>');
          
          cardBody.append(textElem);
          messageElement.append(cardHeader);
          messageElement.append(cardBody);
          
          // Depending on who the sender is, we adjust the alignment and add different background shading
          if (message.sender == 'user') {
            messageElement.addClass('ml-md-auto');  // For right alignment
            messageElement.css('background-color', '#faf5ff');  // Lighter shade of purple
          } else {
            if (message.text.trim().length > 0) {
                initialiseVoteBank(messageElement, message.text, contentId=message.message_id, activeDocId=ConversationManager.activeConversationId);
            }
            messageElement.addClass('mr-md-auto');  // For left alignment
            messageElement.css('background-color', '#f5fcff');  // Lighter shade of blue
          }
          if (message.text.trim().length > 0){
              renderInnerContentAsMarkdown(textElem, function(){
                  if ((textElem.text().length > 300) && (index < array.length - 2)){
                    showMore(null, text=null, textElem=textElem, as_html=true, show_at_start=index >= array.length - 2);
                  }
              });
          }
          
          var statusDiv = $('<div class="status-div d-flex align-items-center"></div>');
          var spinner = $('<div class="spinner-border text-primary" role="status"></div>');
          var statusText = $('<span class="status-text ms-2"></span>');

          statusDiv.append(spinner);
          statusDiv.append(statusText);
          messageElement.append(statusDiv);
          $('#chatView').append(messageElement);
          statusDiv.hide();
          statusDiv.find('.spinner-border').hide();
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
            // showMore(conversationItem, text=null, textElem=$('#summary-text'), as_html=true);
            
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
    $('#messageText').prop('disabled', true);
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
        // $('#linkInput').val('')
        // $('#searchInput').val('')
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

