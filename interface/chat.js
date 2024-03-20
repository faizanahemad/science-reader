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
                $('#linkInput').val('')
                $('#searchInput').val('')
                // Add new conversation to the list
                loadConversations(true).done(function(){
                    // Set the new conversation as the active conversation and highlight it
                    ConversationManager.setActiveConversation(conversation.conversation_id);
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
                }
            }
        });
    },
  
    setActiveConversation: function(conversationId) {
        this.activeConversationId = conversationId;
        // Load and render the messages in the active conversation, clear chat view
        ChatManager.listMessages(conversationId).done(function(messages) {
            ChatManager.renderMessages(conversationId, messages, true);
            $('#messageText').focus();
            
        });
        ChatManager.listDocuments(conversationId).done(function(documents) {
            ChatManager.renderDocuments(conversationId, documents);
        });
        ChatManager.setupAddDocumentForm(conversationId);
        ChatManager.setupDownloadChatButton(conversationId);
        highLightActiveConversation();
        var chatView = $('#chatView');
        chatView.scrollTop(chatView.prop('scrollHeight'));
        setTimeout(function() {
            chatView.scrollTop(chatView.prop('scrollHeight'));
        }, 150);
    }

};

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
            card = ChatManager.renderMessages(conversationId, [serverMessage], false);
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
                                                callback=null, continuous=true, html=answer)
                content_length = answerParagraph.html().length
            }
            if (content_length < 300) {
                var chatView = $('#chatView');
                chatView.scrollTop(chatView.prop('scrollHeight'));
            }
            answer_post_text = answerParagraph.text()
            var statusDiv = card.find('.status-div');
            statusDiv.find('.status-text').text(part['status']);
        }

        if (done) {
            $('#messageText').prop('working', false);
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
                }, continuous=false, html=answer);
                initialiseVoteBank(card, `${messageText} + '\n\n' + ${answer}`, contentId=null, activeDocId=ConversationManager.activeConversationId);
            }
            $('#messageText').focus();
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
    listDocuments: function(conversationId) {
        return $.ajax({
            url: '/list_documents_by_conversation/' + conversationId,
            type: 'GET'
        });
    },
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
                    ChatManager.renderMessages(conversationId, messages);
                });
            }
        });
    },
    deleteDocument: function(conversationId, documentId) {
        return $.ajax({
            url: '/delete_document_from_conversation/' + conversationId + '/' + documentId,
            type: 'DELETE',
            success: function(response) {
                // Reload the conversation
                ChatManager.listDocuments(conversationId).done(function(documents) {
                    ChatManager.renderDocuments(conversationId, documents);
                });
            }
        });
    },
    setupDownloadChatButton: function(conversationId) {
        $('#get-chat-transcript').off().on('click', function() {
            window.open('/list_messages_by_conversation_shareable/' + conversationId, '_blank');
        });
    },
    setupAddDocumentForm: function(conversationId) {
        let doc_modal = $('#add-document-modal-chat')
        $('#add-document-button-chat').off().click(function() {
            $('#add-document-modal-chat').modal({backdrop: 'static', keyboard: false}, 'show');
        });
        function success(response) {
            doc_modal.find('#submit-button').prop('disabled', false);  // Re-enable the submit button
            doc_modal.find('#submit-spinner').hide();  // Hide the spinner
            if (response.status) {
                ChatManager.listDocuments(conversationId)
                    .done(function(documents){
                        doc_modal.modal('hide');
                        ChatManager.renderDocuments(conversationId, documents);
                    })
                    .fail(function(){
                        doc_modal.modal('hide');
                        alert(response.error);
                    })
                // set the new document as the current document
                
            } else {
                alert(response.error);
            }
        }
        function failure(response) {
            doc_modal.find('#submit-button').prop('disabled', false);  // Re-enable the submit button
            doc_modal.find('#submit-spinner').hide();  // Hide the spinner
            alert('Error: ' + response.responseText);
            doc_modal.modal('hide');
        }
    
        function uploadFile(file) {
            var formData = new FormData();
            formData.append('pdf_file', file);
            doc_modal.find('#submit-button').prop('disabled', true);  // Disable the submit button
            doc_modal.find('#submit-spinner').show();  // Display the spinner
            fetch('/upload_doc_to_conversation/' + conversationId, { 
                method: 'POST', 
                body: formData
            })
            .then(response => response.json())
            .then(success)
            .catch(failure);
        }
    
        doc_modal.find('#file-upload-button').off().on('click', function() {
            doc_modal.find('#pdf-file').click();
        });
        
        // Handle file selection
        doc_modal.find('#pdf-file').off().on('change', function(e) {
            var file = $(this)[0].files[0];  // Get the selected file
            // check pdf or doc docx
            if (file && (file.type === 'application/pdf' || file.type === 'application/msword' || file.type === 'application/vnd.openxmlformats-officedocument.wordprocessingml.document')) {
                uploadFile(file);  // Call the file upload function
            }
        });
    
        let dropArea = doc_modal.find('#drop-area').off();
        dropArea.on('dragover', function(e) {
            e.preventDefault();  // Prevent the default dragover behavior
            $(this).css('background-color', '#eee');  // Change the color of the drop area
        });
        dropArea.on('dragleave', function(e) {
            $(this).css('background-color', 'transparent');  // Change the color of the drop area back to its original color
        });
        dropArea.on('drop', function(e) {
            e.preventDefault();  // Prevent the default drop behavior
            $(this).css('background-color', 'transparent');  // Change the color of the drop area back to its original color

            // Check if the dropped item is a file
            if (e.originalEvent.dataTransfer.items) {
                for (var i = 0; i < e.originalEvent.dataTransfer.items.length; i++) {
                    // If the dropped item is a file and it's a PDF, word doc docx
                    if (e.originalEvent.dataTransfer.items[i].kind === 'file' && (e.originalEvent.dataTransfer.items[i].type === 'application/pdf' || e.originalEvent.dataTransfer.items[i].type === 'application/msword' || e.originalEvent.dataTransfer.items[i].type === 'application/vnd.openxmlformats-officedocument.wordprocessingml.document')) {
                        var file = e.originalEvent.dataTransfer.items[i].getAsFile();
                        uploadFile(file);  // Call the file upload function
                    }
                }
            }
        });
        doc_modal.find('#add-document-form').off().on('submit', function(event) {
            event.preventDefault();  // Prevents the default form submission action
            var pdfUrl = doc_modal.find('#pdf-url').val();
            if (pdfUrl) {
                doc_modal.find('#submit-button').prop('disabled', true);  // Disable the submit button
                doc_modal.find('#submit-spinner').show();  // Display the spinner
                apiCall('/upload_doc_to_conversation/' + conversationId, 'POST', { pdf_url: pdfUrl }, useFetch = false)
                    .done(success)
                    .fail(failure);
            } else {
                alert('Please enter a PDF URL');
            }
        });
    },
    renderDocuments: function(conversation_id, documents) {
        console.log(documents);
        var chat_doc_view = $('#chat-doc-view');
        
        // Clear existing documents
        chat_doc_view.children('div').remove();
        
        // Loop through documents
        documents.forEach(function(doc, index) {
            // Create buttons for each document
            var docButton = $('<button></button>')
                .addClass('btn btn-outline-primary btn-sm mr-2 mb-1')
                .text(`#doc_${index + 1}`)
                .attr('data-doc-id', doc.doc_id)
                .attr('data-toggle', 'tooltip')
                .attr('data-trigger', 'hover')
                .attr('data-placement', 'top')
                .attr('data-html', 'true')
                .attr('title', `<b>${doc.title}</br>${doc.source}</b>`).tooltip({delay: {show: 20}});
            // Create Delete 'x' Button
            var deleteButton = $('<i></i>')
                .addClass('fa fa-times')
                .attr('aria-hidden', 'true')
                .attr('aria-label', 'Delete document'); // Accessibility feature
            
            var deleteDiv = $('<div></div>')
                .addClass('btn p-0 btn-sm btn-danger ml-1')
                .append(deleteButton);
            
            // Attach download event to open in a new tab
            docButton.click(function() {
                window.open(`/download_doc_from_conversation/${conversation_id}/${doc.doc_id}`, '_blank');
            });
            
            // Attach delete event
            deleteDiv.click(function(event) {
                event.stopPropagation(); // Prevents the click event from bubbling up to the docButton
                ChatManager.deleteDocument(conversation_id, $(this).parent().data('doc-id'))
                .catch(function() {
                    alert("Error deleting the document.");
                });
            });
            docButton.append(deleteDiv);
            // Create a container for each pair of document and delete buttons
            var container = $('<div></div>')
                .addClass('d-inline-block')
                .append(docButton)
                
                
            // Append the container to the chat_doc_view
            chat_doc_view.append(container);
        });
    },
    deleteMessage: function(conversationId, messageId, index) {
        return $.ajax({
            url: '/delete_message_from_conversation/' + conversationId + '/' + messageId + '/' + index,
            type: 'DELETE',
            success: function(response) {
                // Reload the conversation
                // ChatManager.listMessages(conversationId).done(function(messages) {
                //     ChatManager.renderMessages(conversationId, messages, true);
                //     $('#messageText').focus();
                // });

                // ChatManager.listDocuments(conversationId).done(function(documents) {
                //     ChatManager.renderDocuments(conversationId, documents);
                // });
                // ChatManager.setupAddDocumentForm(conversationId);
                // ChatManager.setupDownloadChatButton(conversationId);
                // highLightActiveConversation();

            },
            error: function(response) {
                alert('Refresh page, delete error, Error: ' + response.responseText);
            }
        });
    },
    renderMessages: function(conversationId, messages, shouldClearChatView) {
        if (shouldClearChatView) {
          $('#chatView').empty();  // Clear the chat view first
        }
        messages.forEach(function(message, index, array) {
          var senderText = message.sender === 'user' ? 'You' : 'Assistant';
            var messageElement = $('<div class="mb-1 mt-0 card w-100 my-1 d-flex flex-column"></div>');
          var delMessage = `<small><button class="btn p-0 ms-2 ml-2 delete-message-button" message-index="${index}" message-id=${message.message_id}><i class="bi bi-trash-fill"></i></button></small>`
          var cardHeader = $(`<div class="card-header text-end" message-index="${index}" message-id=${message.message_id}><small><strong>` + senderText + `</strong>${delMessage}</small></div>`);
          var cardBody = $('<div class="card-body chat-card-body" style="font-size: 0.8rem;"></div>');
          var textElem = $('<p id="message-render-space" class="card-text actual-card-text"></p>');
          textElem.html(message.text.replace(/\n/g, '  \n'))
          
          cardBody.append(textElem);
          messageElement.append(cardHeader);
          messageElement.append(cardBody);
          
          // Depending on who the sender is, we adjust the alignment and add different background shading
          if (message.sender == 'user') {
            // messageElement.addClass('ml-md-auto');  // For right alignment
            messageElement.css('background-color', '#faf5ff');  // Lighter shade of purple
          } else {
            if (message.text.trim().length > 0) {
                initialiseVoteBank(messageElement, message.text, contentId=message.message_id, activeDocId=ConversationManager.activeConversationId);
            }
            // messageElement.addClass('mr-md-auto');  // For left alignment
            messageElement.css('background-color', '#f5fcff');  // Lighter shade of blue
          }
          if (message.text.trim().length > 0){
              renderInnerContentAsMarkdown(textElem, function(){
                  if ((textElem.text().length > 300)){ // && (index < array.length - 2)
                    showMore(null, text=null, textElem=textElem, as_html=true, show_at_start=true); // index >= array.length - 2
                  }
              }, continuous=false, html=message.text.replace(/\n/g, '  \n'));
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
        $(".delete-message-button").off().on("click", function(event) {
            event.preventDefault();
            event.stopPropagation();
            var messageId = $(this).closest('[message-id]').attr('message-id');
            var messageIndex = $(this).closest('[message-index]').attr('message-index');
            $(this).closest('.card').remove();
            ChatManager.deleteMessage(conversationId, messageId, messageIndex);
        });
        // var chatView = $('#chatView');
        // chatView.scrollTop(chatView.prop('scrollHeight'));
        return $('#chatView').find('.card').last();
    },



  
    sendMessage: function(conversationId, messageText, checkboxes, links, search) {
        // Render user's message immediately
        var userMessage = {
            sender: 'user',
            text: messageText
        };
        ChatManager.renderMessages(conversationId, [userMessage], false);

        // Use Fetch API to make request
        let response = fetch('/send_message/' + conversationId, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                'messageText': messageText,
                'checkboxes': checkboxes,
                'links': links,
                'search': search
            })
        });
        responseWaitAndSuccessChecker('/send_message/' + conversationId, response);
        return response;
    }

};


function loadConversations(autoselect=true) {
    var api = '/list_conversation_by_user';
    var request = apiCall(api, 'GET', {})

    request.done(function(data) {
        // sort data by last_updated in descending order
        data.sort(function(a, b) {
            return new Date(b.last_updated) - new Date(a.last_updated);
        });
        // Auto-select the first conversation
        var firstConversation = true;
        $('#conversations').empty();

        // Since we want most recently updated conversations at the top, reverse the data
        data.forEach(function(conversation) {
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
            });

            if (autoselect){
                if (firstConversation) {
                    ConversationManager.setActiveConversation(conversation.conversation_id);
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
    already_rendering = $('#messageText').prop('working')
    if (already_rendering) {
        // also display a small modal for 5 seconds in the UI and automatically close the modal or close the modal on any keypress.
        $('#prevent-chat-rendering').modal('show');

        const closeModal = function () {
            $('#prevent-chat-rendering').modal('hide');
            $(document).off('keydown.prevent-chat-rendering click.prevent-chat-rendering');
        };
        
        setTimeout(function () {
            closeModal();
        }, 5000);

        setTimeout(function () {
            $(document).on('keydown.prevent-chat-rendering click.prevent-chat-rendering', function (e) {
                if (e.key === "Escape" || e.key === "Enter" || e.type === "click") {
                    closeModal();
                }
            });
        }, 200);

        return;
    }
    var messageText = $('#messageText').val();
    if (messageText.trim().length == 0) {
        return;
    }
    // Lets split the messageText and get word count and then check if word count > 1000 then raise alert
    var wordCount = messageText.split(' ').length;
    $('#messageText').val('');  // Clear the messageText field
    $('#messageText').trigger('change');
    $('#messageText').prop('working', true);
    var links = $('#linkInput').val().split('\n');
    var search = $('#searchInput').val().split('\n');
    let options = getOptions('chat-options', 'assistant');
    const booleanKeys = Object.keys(options).filter(key => typeof options[key] === 'boolean');
    const allFalse = booleanKeys.every(key => options[key] === false);
    if ((wordCount > 4000 && !allFalse) || (wordCount > 8000)) {
        alert('Please enter a message with less words');
        $('#messageText').prop('working', false);
        return;
    }

    ChatManager.sendMessage(ConversationManager.activeConversationId, messageText, options, links, search).then(function(response) {
        if (!response.ok) {
            alert('An error occurred: ' + response.status);
            return;
        }
        // Call the renderStreamingResponse function to handle the streaming response
        renderStreamingResponse(response, ConversationManager.activeConversationId, messageText);
        $('#linkInput').val('')
        $('#searchInput').val('')
        $('#messageText').focus();
    });
    var chatView = $('#chatView');
    chatView.scrollTop(chatView.prop('scrollHeight'));
}

$(document).ready(function() {
    
    // $('#chat-assistant-view').hide();
    $("#loader").show();
    // loadConversations();
    // Hide the loader after 10 seconds
    setTimeout(function() {
        $("#loader").hide();
    }, 5000 * 1);  // 1000 milliseconds = 1 seconds
    
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
    // $('#toggleChatDocsView').click();
})

