async function responseWaitAndSuccessChecker(url, responsePromise) {
    // Set a timeout for the API call
    const apiTimeout = setTimeout(() => {
        alert(`The API at ${url} took too long to respond. Reloading the page is advised.`);
        // Reload the page after 5 seconds
        setTimeout(() => {
            location.reload();
        }, 6000);
    }, 75000);  // 1 minute timeout

    try {
        // Wait for the API response
        const response = await responsePromise;

        // Clear the timeout as the API responded
        clearTimeout(apiTimeout);

        // Check the API response status
        if (!response.ok) {
            alert(`An error occurred while calling ${url}: ${response.status}. Reloading the page is advised.`);
            // Reload the page after 5 seconds
            setTimeout(() => {
                location.reload();
            }, 6000);
            return;
        }

        // You can add further code here to process the response if it's OK
        // ...
    } catch (error) {
        // Clear the timeout as an error occurred
        clearTimeout(apiTimeout);

        alert(`An error occurred while calling ${url}: ${error.toString()}. Reloading the page is advised.`);
        // Reload the page after 5 seconds
        setTimeout(() => {
            location.reload();
        }, 6000);
    }
}

function addNewlineToTextbox(textboxId) {
    var messageText = $('#' + textboxId);
    var cursorPos = messageText.prop('selectionStart');
    var v = messageText.val();
    var textBefore = v.substring(0, cursorPos);
    var textAfter = v.substring(cursorPos, v.length);
    messageText.val(textBefore + '\n' + textAfter);
    messageText.prop('selectionStart', cursorPos + 1);
    messageText.prop('selectionEnd', cursorPos + 1);
    if (textAfter.length === 0) {
        var scrollHeight = messageText.prop('scrollHeight');
        messageText.scrollTop(scrollHeight);
    }
    return false;  // Prevents the default action
}

// This function sets the max-height based on the line height
function setMaxHeightForTextbox(textboxId, height=10) {
    var messageText = $('#' + textboxId);
    
    // Determine the line height (might not always be precise, but close)
    var lineHeight = parseFloat(getComputedStyle(messageText[0]).lineHeight);
    
    // Set max-height for 10 lines
    if (!height) {
        height = 10;
    }
    var maxHeight = lineHeight * height;
    messageText.css('max-height', maxHeight + 'px');
    
    // Set overflow to auto to ensure scrollbars appear if needed
    messageText.css('overflow-y', 'auto');
}

function showMore(parentElem, text=null, textElem=null, as_html=false, show_at_start=false){
    
    if (textElem) {
        
        if (as_html){
            var text = textElem.html()
        }
        else {
            var text = textElem.text()
        }
        
    }
    else if ((text) || (typeof text === 'string')) {
        var textElem = $('<small class="summary-text"></small>');
    } else {
        throw "Either text or textElem must be provided to `showMore`"
    }
    
    if (as_html) {
        
        var moreText = $('<span class="more-text" style="display:none;"></span>')
        moreText.html(text)
        moreText.find('.show-more').each(function(){$(this).remove();})
        shortText = moreText.text().slice(0, 10);
        var lessText = $(`<span class="less-text" style="display:block;">${shortText}</span>`)
        previous_sm = textElem.find('.show-more').length
        var smClick = $(' <a href="#" class="show-more">[show]</a> ')
        textElem.empty()
        textElem.append(lessText)
        textElem.append(smClick)
        
        textElem.append(moreText)
        
        moreText.append(smClick.clone())
    }
    else {
        var moreText = text.slice(20);
        if(moreText) {
            var lessText = text.slice(0, 20);
            textElem.append(lessText + '<span class="more-text" style="display:none;">' + moreText + '</span>' + ' <a href="#" class="show-more">[show]</a>');
        } else {
            textElem.append(text);
        }
    }

    if (parentElem) {
        parentElem.append(textElem);
    }
    
    function toggle(event){
        if (event) {
            event.preventDefault();
            event.stopPropagation();
        }
        var moreText = textElem.find('.more-text');
        var lessText = textElem.find('.less-text');
        if(moreText.is(':visible')) {
            moreText.hide();
            if (lessText) {
                lessText.show()
            }
            textElem.find('.show-more').each(function(){$(this).text('[show]');})
            $(this).text('[show]');
        } else {
            moreText.show();
            if (lessText) {
                lessText.hide()
            }
            textElem.find('.show-more').each(function(){$(this).text('[hide]');})
            $(this).text('[hide]');
        }
    }
    
    if (show_at_start) {
        toggle(null);
    }
    

    textElem.find('.show-more').click(toggle);
}

function disableMainFunctionality() {
    // darken the screen
    $("body").append('<div id="overlay" style="position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0, 0, 0, 0.6); z-index: 999999;"><div class="spinner-border text-primary" role="status" style="position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%);"><span class="sr-only">Loading...</span></div></div>');

    // scroll to the OpenAI key input field
    $('html, body').animate({
        scrollTop: $("#openAIKey").offset().top
    }, 1000);
}

function enableMainFunctionality() {
    // remove the overlay and spinner
    $("#overlay").remove();

    // scroll back to the top of the page
    $('html, body').animate({
        scrollTop: 0
    }, 1000);
}

function verifyOpenAIKeyAndFetchModels(apiKey) {
    // Make a GET request to OpenAI API
    $.ajax({
        url: "https://api.openai.com/v1/models",
        type: "GET",
        beforeSend: function(xhr) {
            xhr.setRequestHeader('Authorization', 'Bearer ' + apiKey);
        },
    })
    .done(function(response) {
        console.log(response.data);

        // Extract model ids and add to the keyStore
        var modelIds = response.data.map(function(model) {
            return model.id;
        });
        keyStore['openai_models_list'] = modelIds;

        // Now that we have successfully fetched the models, we can set the keys on the server
        setKeysOnServer();

        // enable the main functionality of the page
        enableMainFunctionality();
    })
    .fail(function(jqXHR, textStatus, errorThrown) {
        console.log("Error: " + errorThrown);
        alert('Failed to verify OpenAI Key or fetch the list of models. Please check the console for more details.');

        // highlight the OpenAI key input field
        document.getElementById('openAIKey').style.borderColor = "red";
        window.scrollTo(0, document.getElementById('openAIKey').offsetTop);

        // if the function was called due to an input event, we need to disable the main functionality until a valid key is provided
        if (apiKey !== keyStore['openAIKey']) {
            // disableMainFunctionality();
            pass
        }
    });
}
function initialiseVoteBank(cardElem, text, contentId=null, activeDocId=null) {
    let voteCountElem = $('<p>').addClass('vote-count');
    let upvoteBtn = $('<button>').addClass('vote-btn').addClass('upvote-btn').text('👍');
    let downvoteBtn = $('<button>').addClass('vote-btn').addClass('downvote-btn').text('👎');
    let copyBtn = $('<button>').addClass('vote-btn').addClass('copy-btn').text('📋');
    copyBtn.click(function() {
        // Here we get the card text and copy it to the clipboard
        // let cardText = cardElem.text().replace(/\[show\]|\[hide\]/g, '');
        copyToClipboard(cardElem);
    });
    
    let voteBox = $('<div>').addClass('vote-box').css({
        'position': 'absolute',
        'top': '5px',
        'right': '20px'
    });
    voteBox.append(copyBtn, upvoteBtn, voteCountElem, downvoteBtn);
    cardElem.append(voteBox);

    function updateVoteCount() {
        var request = $.ajax({
            url: '/getUpvotesDownvotesByQuestionId/' + contentId,
            type: 'POST',
            data: JSON.stringify({doc_id: activeDocId, question_text: text, question_id: contentId}),
            dataType: 'json',
            contentType: 'application/json',
        });
        
        
        
        request.done(function(data) {
            if (data.length > 0) {
                var upvotes = data[0][0];
                var downvotes = data[0][1];
            }
            else {
                var upvotes = 0;
                var downvotes = 0;
            }
            
            voteCountElem.text(upvotes + '/' + (upvotes + downvotes));
        }).fail(
            function(data) {
                var upvotes = 0;
                var downvotes = 0;
                voteCountElem.text(upvotes + '/' + (upvotes + downvotes));
            }
        );
    }

    function checkUserVote() {
        
        var request = $.ajax({
            url: '/getUpvotesDownvotesByQuestionIdAndUser',
            type: 'POST',
            data: JSON.stringify({doc_id: activeDocId, question_text: text, question_id: contentId}),
            dataType: 'json',
            contentType: 'application/json',
        });
        
        request.done(function(data) {
            if (data.length > 0) {
                var upvotes = data[0][0];
                var downvotes = data[0][1];
            }
            else {
                var upvotes = 0;
                var downvotes = 0;
            }
            if (upvotes > 0) {
                upvoteBtn.addClass('voted');
                downvoteBtn.removeClass('voted');
            }
            if (downvotes > 0) {
                downvoteBtn.addClass('voted');
                upvoteBtn.removeClass('voted');
            }
        });
    }
    
    function getCheckedValues(modalID) {
        let checkedValues = $(modalID + ' input[type=checkbox]:checked').map(function() {
            return this.value;
        }).get();
        return checkedValues;
    }

    function getComments(modalID) {
        return $(modalID + ' textarea').val();
    }

    function sendFeedback(feedbackType) {
        let modalID = '#' + feedbackType + '-feedback-modal';
        let feedbackData = {
            feedback_type: feedbackType,
            question_id: contentId,
            feedback_items: getCheckedValues(modalID),
            comments: getComments(modalID),
            doc_id: activeDocId,
            question_text: text
        };
        $(modalID).modal('hide');
        apiCall('/addUserQuestionFeedback', 'POST', feedbackData).always(function() {
            // After the feedback is successfully submitted, clear the checkboxes and textarea
            $(modalID + ' input[type=checkbox]').prop('checked', false);
            $(modalID + ' textarea').val('');
        });;
    }

    upvoteBtn.click(function() {
        apiCall('/addUpvoteOrDownvote', 'POST', {question_id: contentId, doc_id: activeDocId, upvote: 1, downvote: 0, question_text: text}).done(function() {
            upvoteBtn.addClass('voted');
            downvoteBtn.removeClass('voted');
            updateVoteCount();
            checkUserVote();
            
            $('#positive-feedback-modal').modal('show');
            $('.submit-positive-feedback').off('click').click(function() {
                sendFeedback('positive');
            });
        });
        
    });

    downvoteBtn.click(function() {
        apiCall('/addUpvoteOrDownvote', 'POST', {question_id: contentId, doc_id: activeDocId, upvote: 0, downvote: 1, question_text: text}).done(function() {
            upvoteBtn.addClass('voted');
            downvoteBtn.removeClass('voted');
            updateVoteCount();
            checkUserVote();
            
            $('#negative-feedback-modal').modal('show');
            $('.submit-negative-feedback').off('click').click(function() {
                sendFeedback('negative');
            });
        });
    });

    updateVoteCount();
    checkUserVote();
}
const markdownParser = new marked.Renderer();
marked.setOptions({
    renderer: markdownParser,
    highlight: function(code, language) {
        const validLanguage = hljs.getLanguage(language) ? language : 'plaintext';
        return hljs.highlight(validLanguage, code).value;
    },
    pedantic: false,
    gfm: true,
    breaks: false,
    sanitize: false,
    smartLists: true,
    smartypants: true,
    xhtml: true
});
markdownParser.codespan = function(text) {
  return '<code>' + text + '</code>';
};
markdownParser.code = function(code, language) {
    var validLang = !!(language && hljs.getLanguage(language));
    var highlighted = validLang ? hljs.highlight(code, { language }).value : code;
    return '<div class="code-block">' +
           '<div class="code-header">' +
           '<span class="code-language">' + (language || 'plaintext') + '</span>' +
           '<button class="copy-code-btn">Copy</button>' +
           '</div>' +
           '<pre><code class="hljs ' + (language || '') + '">' +
           highlighted +
           '</code></pre>' +
           '</div>';
};


function renderInnerContentAsMarkdown(jqelem, callback=null, continuous=false, html=null){
    parent = jqelem.parent()
    elem_id = jqelem.attr('id');
    elem_to_render_in = jqelem
    brother_elem_id = elem_id + "-md-render"
    if (continuous) {
        brother_elem = parent.find('#' + brother_elem_id);
        if (!brother_elem.length) {
            var brother_elem = $('<p/>', {id: brother_elem_id})
            parent.append(brother_elem);
        }
        jqelem.hide();
        brother_elem.show();
        elem_to_render_in = brother_elem
        
    } else {
        jqelem.show();
        brother_elem = parent.find('#' + brother_elem_id);
        if (brother_elem.length) {
            brother_elem.hide();
        }
    }
    
    if (html==null){
        try {
            html = jqelem.html()
        } catch(error) {
            try{html = jqelem[0].innerHTML} catch (error) {html = jqelem.innerHTML}
        }
    }
    var htmlChunk = marked.marked(html, { renderer: markdownParser });
    htmlChunk = removeEmTags(htmlChunk);
    try{
        elem_to_render_in.empty();
    } catch(error){
        try{
            elem_to_render_in[0].innerHTML=''
        } catch (error) {elem_to_render_in.innerHTML=''}
    }
    try{
        elem_to_render_in.append(htmlChunk)
    } catch(error){
        try{
            elem_to_render_in[0].innerHTML=htmlChunk
        } catch (error) {
            elem_to_render_in.innerHTML=htmlChunk
        }
    }
    
    mathjax_elem = elem_to_render_in[0]
    if (mathjax_elem === undefined) {
        mathjax_elem = jqelem
    }
    MathJax.Hub.Queue(["Typeset", MathJax.Hub, mathjax_elem]);
    if (callback) {
        MathJax.Hub.Queue(callback)
    }
    code_elems = $(elem_to_render_in).find('code')
    Array.from(code_elems).forEach(function(code_elem){
        // hljs.highlightBlock(code_elem);
    });
}

function loadDocumentsForMultiDoc(searchResultsAreaId, tagsAreaId, search_term='', activeDocId=null) {
    var api;
    var search_mode;

    if (search_term.length > 0) {
        api = '/search_document?text='+ search_term;
        search_mode = true;
    } else {
        api = '/list_all';
        search_mode = false;
    }

    var request = apiCall(api, 'GET', {});
    request.done(function(data) {
        var searchResultsArea = $('#' + searchResultsAreaId);
        searchResultsArea.empty();

        var resultList = $('<ol></ol>'); // Create an ordered list
        var documentIds = [];
        $('.document-tag').each(function() {
            documentIds.push($(this).attr('data-doc-id'));
        });
        if (activeDocId) {
            data = data.filter(doc=>doc.doc_id !== activeDocId);
        }
        data.filter(doc=>!documentIds.includes(doc.doc_id)).forEach(function(doc, index) {
            var docItem = $(`
                <li class="my-2">
                    <a href="#" class="search-result-item d-block" data-doc-id="${doc.doc_id}">${doc.title}</a>
                </li>
            `);
            docItem.click(function(event) {
                event.preventDefault();
                addDocumentTags(tagsAreaId, [doc]);
            });
            resultList.append(docItem); // Append list items to the ordered list
        });
        searchResultsArea.append(resultList); // Append the ordered list to the search results area
    });

    return request;
}


function addDocumentTags(tagsAreaId, data){
    
    data.forEach(function(doc) {
        var docTag = $(`
            <div class="document-tag bg-light border rounded mb-2 mr-2 p-2 d-inline-flex align-items-center" data-doc-id="${doc.doc_id}">
                <span class="me-2">${doc.title}</span>
                <button class="delete-tag-button btn btn-sm btn-danger">Delete</button>
            </div>`);
        var count = $('#' + tagsAreaId).children().length;
        var limit = 4
        if (count > limit - 1){
            alert(`you cannot add more than ${limit} documents for Multiple Doc Search`);
        }
        else {$('#' + tagsAreaId).append(docTag);}
        // Handle click events for the delete button
        $('.delete-tag-button').click(function(event) {
            event.preventDefault();
            event.stopPropagation();
            $(this).parent().remove();
        });
    });
}

function copyToClipboard(textElem, mode="text") {
    // var text = textElem.text().replace(/\[show\]|\[hide\]/g, '');
    if (mode === "text") {
        var textElements = $(textElem);
        // .find('p, span, div, code, h1, h2, h3, h4, h5, h6, strong, em');
    }
    else if (mode === "code") {
        var textElements = $(textElem).closest('.code-block').find('code');
        // .find('p, span, div, code');
    }
    else {
        var textElements = $(textElem).find('p, span, div, code, h1, h2, h3, h4, h5, h6, strong, em, input');
    }
    
    var textToCopy = "";
    textElements.each(function() {
        var $this = $(this);
        if ($this.is("input, textarea")) {
            textToCopy += $this.val().replace(/\[show\]|\[hide\]/g, '') + "\n";
        } else {
            textToCopy += $this.text().replace(/\[show\]|\[hide\]/g, '') + "\n";
        }
    });

    if (navigator.clipboard && navigator.clipboard.writeText) {
        // New Clipboard API
        navigator.clipboard.writeText(textToCopy).then(() => {
            console.log("Text successfully copied to clipboard")
        }).catch(err => {
            console.warn("Copy to clipboard failed.", err);
        });
    } else {
        // Fallback to the older method for incompatible browsers
        var textarea = document.createElement("textarea");
        textarea.textContent = textToCopy;
        document.body.appendChild(textarea);
        textarea.select();
        try {
            return document.execCommand("copy");
        } catch (ex) {
            console.warn("Copy to clipboard failed.", ex);
            return false;
        } finally {
            document.body.removeChild(textarea);
        }
    }
}



function initSearchForMultipleDocuments(searchBoxId, searchResultsAreaId, tagsAreaId, activeDocId=null){
    var lastTimeoutId = null;  
    var previousSearchLength = 0;
    var searchBox = $('#' + searchBoxId);
    $('#' + tagsAreaId).empty();

    searchBox.on('input', function() {
        var currentSearchLength = searchBox.val().length;

        if (lastTimeoutId !== null) {
            clearTimeout(lastTimeoutId);
        }

        lastTimeoutId = setTimeout(function() {
            currentSearchLength = searchBox.val().length;
            if (currentSearchLength >= 5 || (previousSearchLength >= 5 && currentSearchLength < 5)) {  
                loadDocumentsForMultiDoc(searchResultsAreaId, tagsAreaId, searchBox.val(), activeDocId);
            } else if (currentSearchLength === 0 && previousSearchLength >= 1) {
                loadDocumentsForMultiDoc(searchResultsAreaId, tagsAreaId, '', activeDocId);
            }
            previousSearchLength = currentSearchLength;

            lastTimeoutId = null; 
        }, 400);
    });
}




function addOptions(parentElementId, type, activeDocId=null) {
    var checkBoxIds = [
        type==="assistant"?`${parentElementId}-${type}-use-google-scholar`:`${parentElementId}-${type}-use-references-and-citations-checkbox`,
        `${parentElementId}-${type}-perform-web-search-checkbox`,
        `${parentElementId}-${type}-use-multiple-docs-checkbox`,
    ];
    slow_fast = `${parentElementId}-${type}-provide-detailed-answers-checkbox`
    var checkboxOneText = type==="assistant"?"Research":"References and Citations";
    var disabled = type==="assistant"?"":"disabled";

    

    $(`#${parentElementId}`).append(
        `<div style="display: flex;">` +

        `<div class="form-check form-check-inline" style="margin-right: 10px;"><input class="form-check-input" id="${checkBoxIds[0]}" type="checkbox" ${disabled}><label class="form-check-label" for="${checkBoxIds[0]}">${checkboxOneText}</label></div>` +

        `<div class="form-check form-check-inline" style="margin-right: 10px;"><input class="form-check-input" id="${checkBoxIds[1]}" type="checkbox"><label class="form-check-label" for="${checkBoxIds[1]}">Web Search</label></div>` +

        `<div class="form-check form-check-inline" style="margin-right: 10px;"><input class="form-check-input" id="${checkBoxIds[2]}" type="checkbox"><label class="form-check-label" for="${checkBoxIds[2]}">Your Docs</label></div>` +
        
        (type === "assistant" ? `
        
    <div class="form-check form-check-inline" id="${slow_fast}" style="line-height: 0.9;">
    <div style="border: 1px solid #ccc; padding: 2px; border-radius: 12px; display: inline-flex; align-items: center;">
        <div style="margin-left: auto; margin-right: 5px;">Depth</div>
        <div style="display: flex; flex-direction: column; align-items: center; margin-right: 5px;">
            <input type="radio" name="${slow_fast}Options" id="${slow_fast}1" value="1" autocomplete="off">
            <label for="${slow_fast}1"><small>1</small></label>
        </div>
        <div style="display: flex; flex-direction: column; align-items: center; margin-right: 5px;">
            <input type="radio" name="${slow_fast}Options" id="${slow_fast}2" value="2" autocomplete="off" checked>
            <label for="${slow_fast}2"><small>2</small></label>
        </div>
        <div style="display: flex; flex-direction: column; align-items: center; margin-right: 5px;">
            <input type="radio" name="${slow_fast}Options" id="${slow_fast}3" value="3" autocomplete="off">
            <label for="${slow_fast}3"><small>3</small></label>
        </div>
        <div style="display: flex; flex-direction: column; align-items: center; margin-right: 5px;">
            <input type="radio" name="${slow_fast}Options" id="${slow_fast}4" value="4" autocomplete="off">
            <label for="${slow_fast}4"><small>4</small></label>
        </div>
    </div>
    </div>

` : '') +

        (type === "assistant" ? `
        
    <div class="form-check form-check-inline" id="enablePreviousMessagesContainer" style="line-height: 0.9;">
    <div style="border: 1px solid #ccc; padding: 2px; border-radius: 12px; display: inline-flex; align-items: center;">
        <div style="margin-left: auto; margin-right: 5px;">History</div>
        <div style="display: flex; flex-direction: column; align-items: center; margin-right: 5px;">
            <input type="radio" name="historyOptions" id="historyBan" value="-1" autocomplete="off">
            <label for="historyBan"><small><i class="fas fa-ban"></i></small></label>
        </div>
        <div style="display: flex; flex-direction: column; align-items: center; margin-right: 5px;">
            <input type="radio" name="historyOptions" id="history0" value="0" autocomplete="off">
            <label for="history0"><small>0</small></label>
        </div>
        <div style="display: flex; flex-direction: column; align-items: center; margin-right: 5px;">
            <input type="radio" name="historyOptions" id="history1" value="1" autocomplete="off">
            <label for="history1"><small>1</small></label>
        </div>
        <div style="display: flex; flex-direction: column; align-items: center; margin-right: 5px;">
            <input type="radio" name="historyOptions" id="history2" value="2" autocomplete="off">
            <label for="history2"><small>2</small></label>
        </div>
        <div style="display: flex; flex-direction: column; align-items: center; margin-right: 5px;">
            <input type="radio" name="historyOptions" id="historyInfinite" value="infinite" autocomplete="off" checked>
            <label for="historyInfinite"><small>∞</small></label>
        </div>
        
    </div>
    </div>

` : '') +
        (type==="assistant"?`<button id="deleteLastTurn" class="btn btn-danger rounded-pill" style="margin-left: 10px;">Del Last Turn</button>`:'') + 
        (type==="assistant"?`<div class="input-group-append"><button id="sendMessageButton" class="btn btn-success rounded-pill" style="margin-left: 10px;"><i class="fas fa-paper-plane"></i></button></div>`:'') + 
        `</div>`
    );


    // Elements for Multiple Documents option
    var searchBox = $(`<input id="${parentElementId}-${type}-search-box" type="text" placeholder="Search for documents..." style="display: none;">`);
    var searchResultsArea = $(`<div id="${parentElementId}-${type}-search-results" style="display: none;"></div>`);
    var docTagsArea = $(`<div id="${parentElementId}-${type}-document-tags" style="display: none;"></div>`);

    // Add them to the parent element
    $(`#${parentElementId}`).append(searchBox, searchResultsArea, docTagsArea);

    // Add event handlers to make checkboxes mutually exclusive
    checkBoxIds.forEach(function(id, index) {
        $('#' + id).change(function() {
            if(this.checked) {
                checkBoxIds.forEach(function(otherId, otherIndex) {
                    if(index !== otherIndex) {
                        var otherCheckBox = $('#' + otherId);
                        if(otherCheckBox.is(':checked')) {
                            otherCheckBox.prop('checked', false).trigger('change');
                        }
                    }
                });
            }
        });
    });

    // Add an event handler on the Multiple Docs checkbox
    $('#' + checkBoxIds[2]).change(function() {
        if(this.checked) {
            // If checked, display the search box, search results area and document tags area
            searchBox.css('display', 'block');
            searchResultsArea.css('display', 'block');
            docTagsArea.css('display', 'block');

            // Initialize search functionality
            initSearchForMultipleDocuments(`${parentElementId}-${type}-search-box`, `${parentElementId}-${type}-search-results`, `${parentElementId}-${type}-document-tags`, activeDocId);
        } else {
            // If unchecked, hide the search box, search results area and document tags area
            searchBox.css('display', 'none');
            searchResultsArea.css('display', 'none');
            docTagsArea.css('display', 'none');
            searchBox.val('');
            searchResultsArea.empty();
            docTagsArea.empty();
        }
    });
    if (type === 'assistant') {
        $('#deleteLastTurn').click(function() {
            if (ConversationManager.activeConversationId) {
                ChatManager.deleteLastMessage(ConversationManager.activeConversationId);
            }
        });
    }
}



function getOptions(parentElementId, type) {
    checkBoxOptionOne = type==="assistant" ? "googleScholar":"use_references_and_citations"
    optionOneChecked = $(type==="assistant"?`#${parentElementId}-${type}-use-google-scholar`:`#${parentElementId}-${type}-use-references-and-citations-checkbox`).is(':checked');
    slow_fast = `${parentElementId}-${type}-provide-detailed-answers-checkbox`
    values = {
        perform_web_search: $(`#${parentElementId}-${type}-perform-web-search-checkbox`).is(':checked'),
        use_multiple_docs: $(`#${parentElementId}-${type}-use-multiple-docs-checkbox`).is(':checked'),
    };
    let speedValue = $(`input[name='${slow_fast}Options']:checked`).val();
    values['provide_detailed_answers'] = speedValue;
    values[checkBoxOptionOne] = optionOneChecked;
    if (type === "assistant") {
        let historyValue = $("input[name='historyOptions']:checked").val();
        values['enable_previous_messages'] = historyValue;
    }
    var documentIds = [];
    $(`#${parentElementId}`).find('.document-tag').each(function() {
        documentIds.push($(this).attr('data-doc-id'));
    });
    values['additional_docs_to_read'] = documentIds;
    return values
}

function resetOptions(parentElementId, type) {
    $(type==="assistant"?`${parentElementId}-${type}-use-google-scholar`:`${parentElementId}-${type}-use-references-and-citations-checkbox`).prop('checked', false);
    $(`#${parentElementId}-${type}-perform-web-search-checkbox`).prop('checked', false);
    $(`#${parentElementId}-${type}-use-multiple-docs-checkbox`).prop('checked', false);

    
    var searchBox = $(`#${parentElementId}-${type}-search-box`);
    var searchResultsArea = $(`#${parentElementId}-${type}-search-results`);
    var docTagsArea = $(`#${parentElementId}-${type}-document-tags`);
    searchBox.css('display', 'none');
    searchResultsArea.css('display', 'none');
    docTagsArea.css('display', 'none');
    searchBox.val('');
    searchResultsArea.empty();
    docTagsArea.empty();
    
    
}

function removeOptions(parentElementId, type) {
    $(type==="assistant"?`#${parentElementId}-${type}-use-google-scholar`:`#${parentElementId}-${type}-use-references-and-citations-checkbox`).parent().remove();
    $(`#${parentElementId}-${type}-perform-web-search-checkbox`).parent().remove();
    $(`#${parentElementId}-${type}-use-multiple-docs-checkbox`).parent().remove();
    $(`#${parentElementId}-${type}-provide-detailed-answers-checkbox`).parent().remove();
    
    $(`[id$="${type}-search-box"]`).remove();
    $(`[id$="${type}-document-tags"]`).remove();
    $(`[id$="${type}-search-results"]`).remove();
    if (type === "assistant") {
        $('#enablePreviousMessagesContainer').remove();
        $('#deleteLastTurn').remove();
        $('#sendMessageButton').remove();
    }
}



var keyStore = {
    openAIKey: '',
    mathpixId: '',
    mathpixKey: '',
    cohereKey: '',
    ai21Key: '',
    bingKey: '',
    serpApiKey: '',
    googleSearchCxId: '',
    googleSearchApiKey: '',
    scrapingBrowserUrl: '',
    activeDocId: '',
}

function setKeysOnServer() {
    apiCall("/set_keys", "POST", keyStore, false).done(function(data) {
        console.log('Success:', data);
    })
    .fail(function() {
        alert('Error! Failed to set keys');
    });

}

function createAndInitPseudoUserId() {
    pseudoUserId = localStorage.getItem('pseudoUserId') || '';
    if (pseudoUserId.length === 0) {
        try {
            pseudoUserId = crypto.randomUUID();
        } catch (error) {
            console.log('Failed to generate pseudo user id using crypto.randomUUID()');
            // use uuid library as fallback
            pseudoUserId = uuid.v4();
        }

        localStorage.setItem('pseudoUserId', pseudoUserId);
    }
    keyStore['pseudoUserId'] = pseudoUserId
    apiCall('/login', 'GET', {email: pseudoUserId})
        .done(function(data) {
                console.log(`Pseudo Id set ${pseudoUserId}`);
                if (window.location.pathname.startsWith('/login')) {
                    window.location.assign('/interface');
                }
                
            })
        .fail(function(jqXHR, textStatus, errorThrown) {
            // You can log all the parameters to see which one gives you the error message you're interested in.
            // 'jqXHR' is the full response object, 'textStatus' is a description of the type of error,
            // and 'errorThrown' is the textual portion of the HTTP status, such as "Not Found" or "Internal Server Error."
            console.log("HTTP Status Code: " + jqXHR.status);
            console.log("Error Message: " + errorThrown);
            console.log("Response: " + jqXHR);
            console.log(`An error occurred: ${textStatus}, ${errorThrown}`);
        })
}

// function to update All Keys as JSON text field with current keyStore
function updateAllKeysAsJson() {
    document.getElementById('allKeysAsJson').value = JSON.stringify(keyStore, null, 0);
}

// function to set keys from JSON text field to individual keys
function setKeysFromJson() {
    let allKeysAsJsonElem = document.getElementById('allKeysAsJson');
    try {
        const newKeys = JSON.parse(allKeysAsJsonElem.value);
        // merge newKeys and keyStore
        Object.assign(keyStore, newKeys);
        for (const key in keyStore) {
            // update the input field value
            let keyElement = document.getElementById(key);
            localStorage.setItem(key, keyStore[key]);
            if (keyElement) {
                keyElement.value = keyStore[key];
            }
        }
        // set keys on server
        setKeysOnServer();
        // update allKeysAsJson text field with current keyStore
        updateAllKeysAsJson();
    } catch (error) {
        alert('Invalid JSON format in All Keys field: ' + error.message);
    }
}

function initialiseKeyStore() {
    for (const key of Object.keys(keyStore)) {
        if (key === 'pseudoUserId') {
            continue;
        }
        keyString = localStorage.getItem(key) || '';
        elem = document.getElementById(key)
        keyStore[key] = keyString
        
        if (elem) {
            elem.value = keyString
            elem.addEventListener('input', function (evt) {
                keyString = evt.target.value;
                keyStore[key] = keyString
                localStorage.setItem(key, keyString);
                // update All Keys as JSON text field whenever individual key changes
                updateAllKeysAsJson();

                // If OpenAI key is provided, verify it and fetch the list of models
                if (key === 'openAIKey' && keyString) {
                    // disableMainFunctionality();
                    verifyOpenAIKeyAndFetchModels(keyString);
                } else {
                    setKeysOnServer();
                }
            });
        }
    }

    // if OpenAI key is already in local storage, verify it and fetch the list of models in the background
    if (keyStore['openAIKey']) {
        verifyOpenAIKeyAndFetchModels(keyStore['openAIKey']);
    }
    createAndInitPseudoUserId();
    setKeysOnServer();

    // Initialise All Keys as JSON text field
    updateAllKeysAsJson();
    // Add event listener to All Keys as JSON text field
    document.getElementById('allKeysAsJson').addEventListener('input', setKeysFromJson);
    // Add event listener to Copy button
    document.getElementById('copyButton').addEventListener('click', function () {
        let allKeysAsJsonElem = document.getElementById('allKeysAsJson');
        copyToClipboard(allKeysAsJsonElem);
    });
}



function isAbsoluteUrl(url) {
  // A simple way to check if the URL is absolute is by looking for the presence of '://'
  return url.indexOf('://') > 0;
};


function apiCall(url, method, data, useFetch = false) {
//     url = appendKeyStore(url);

    if(useFetch) {
        const options = {
            method: method,
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(data),
        };

        if (method === 'GET') {
            delete options.body;
        } 
        let response = fetch(url, options);
        responseWaitAndSuccessChecker(url, response);
        return response
    } else {
        if (method === 'GET') {
            return $.get(url, data);
        } else if (method === 'POST') {
            return $.post({url: url, data: JSON.stringify(data), contentType: 'application/json'});
        } else if (method === 'DELETE') {
            return $.ajax({
                url: url,
                type: 'DELETE'
            });
        }
        // Add other methods as needed
    }
}



function removeEmTags(htmlChunk) {
    // Create a regular expression that matches <em> and </em> tags
    var regex = /<\/?em>/g;

    // Use the replace method to replace the matched tags with an empty string
    var newHtmlChunk = htmlChunk.replace(regex, '_');
    var regex = /<\/?i>/g;
    var newHtmlChunk = newHtmlChunk.replace(regex, '_');

    return newHtmlChunk;
}


$(document).ready(function() {
    const options = {
        throwOnError: false,
        trust: true
    };
    
    var activeDocId = localStorage.getItem('activeDocId') || null;
    var pdfUrl = null;
    
    
    
    function createAndPopulateOneTable(data, identifier){
        if ( $.fn.dataTable.isDataTable(identifier) ) {
            var table = $(identifier).DataTable();
        }
        else {
            $(`${identifier} tfoot th`).each(function () {
                var title = $(this).text();
                $(this).html('<input type="text" placeholder="Search ' + title + '" />');
            });
            var table = $(identifier).DataTable({
                data: data,
                searchPanes: {
                    viewTotal: true
                },
                dom: 'Plfrtip',
                columns: [
                    { data: 'ArXiv' },
                    { 
                        data: 'abstract',
                        render: function(data, type, row) {
                            // Shorten the abstract to 100 characters. Change this number to suit your needs.
                            var shortenedAbstract = data.substr(0, 100);

                            // Check if the abstract was shortened
                            var wasShortened = data.length > 100;

                            // Add an ellipsis to the shortened abstract if it was shortened
                            if (wasShortened) {
                                shortenedAbstract += '...';
                            }

                            // The abstract cell will contain the full abstract (hidden), the shortened abstract, and
                            // a '[show]' link (if the abstract was shortened). When the '[show]' link is clicked,
                            // it will show the full abstract and hide the shortened abstract and itself, and show a '[hide]'
                            // link instead. When the '[hide]' link is clicked, it will do the reverse.
                            return `
                                <span class="full-abstract" style="display: none;">${data} <a href="#" class="hide-abstract-link">[hide]</a></span>
                                <span class="short-abstract">${shortenedAbstract}</span>
                                ${wasShortened ? '<a href="#" class="show-abstract-link">[show]</a>' : ''}
                            `;
                        }
                    },
                    { data: 'citationCount' },
                    {
                        data: null,
                        render: function(data, type, row) {
                            let journal = row.journal || '';
                            let venue = row.venue || '';

                            // If both are not available, return an empty string
                            if (!journal && !venue) {
                                return '';
                            }

                            // If journal is 'ArXiv' or 'arXiv.org', prefer the venue unless the venue is empty
                            if ((journal === 'ArXiv' || journal === 'arXiv.org') && venue) {
                                return venue;
                            }

                            // If venue is 'ArXiv' or 'arXiv.org', prefer the journal unless the journal is empty
                            if ((venue === 'ArXiv' || venue === 'arXiv.org') && journal) {
                                return journal;
                            }

                            // Choose the longer value if both are available
                            if (journal.length >= venue.length) {
                                return journal;
                            } else {
                                return venue;
                            }
                        }
                    },
                    { data: 'paperId' },
                    { data: 'publicationDate' },
                    { data: 'referenceCount' },
                    { data: 'title' },
                    { data: 'tldr' },
                    { 
                        data: null, 
                        render: function (data, type, row) {
                            return `<a href="${row.url}">Link</a>`
                        }
                    
                    },
                    { data: 'year' },
                    { 
                        data: null,
                        render: function ( data, type, row ) {
                            if (!row.extended_abstract) {
                                return '<button class="btn btn-primary get-details" data-paper-id="' + row.paperId + '">Get Details</button>';
                            } else {
                                var extended_abstract = row.extended_abstract;
                                var shortenedAbstract = extended_abstract.substr(0, 100);
                                var wasShortened = extended_abstract.length > 100;
                                if (wasShortened) {
                                    shortenedAbstract += '...';
                                }

                                return `
                                    <span class="full-abstract" style="display: none;">${extended_abstract} <a href="#" class="hide-abstract-link">[hide]</a></span>
                                    <span class="short-abstract">${shortenedAbstract}</span>
                                    ${wasShortened ? '<a href="#" class="show-abstract-link">[show]</a>' : ''}
                                `;
                            }
                        }
                    },
                ],
                columnDefs: [
                    {
                        targets: [0, 4, 5, 6, 8],  // Index of 'paperId' column
                        visible: false
                    }
                ],
                initComplete: function () {
                    // Apply the search
                    this.api()
                        .columns()
                        .every(function () {
                            var that = this;

                            $('input', this.footer()).on('keyup change clear', function () {
                                if (that.search() !== this.value) {
                                    that.search(this.value).draw();
                                }
                            });
                        });
                        
                },
            });
        }
        table.clear().rows.add(data).draw();
        $(`${identifier} tfoot tr`).appendTo(`${identifier} thead`);
        
        $(identifier).on('click', '.show-abstract-link', function(e) {
            e.preventDefault();

            // Show the full abstract and '[hide]' link, and hide the shortened abstract and '[show]' link
            $(this).siblings('.full-abstract').show();
            $(this).siblings('.short-abstract').hide();
            $(this).hide();
        });

        $(identifier).on('click', '.hide-abstract-link', function(e) {
            e.preventDefault();

            // Hide the full abstract and '[hide]' link, and show the shortened abstract and '[show]' link
            $(this).parent().hide();
            $(this).parent().siblings('.short-abstract, .show-abstract-link').show();
        });
        
        
        $(identifier).on('click', '.get-details', async function() {
            var paperId = $(this).data('paper-id');

            // Make the button disabled and change the text to "Loading..."
            $(this).prop('disabled', true).text('Loading...');

            // Create a new span element for the extended abstract
            var extendedAbstractSpan = $('<span>').addClass('full-abstract').hide();
            var shortenedAbstractSpan = $('<span>').addClass('short-abstract').hide();
            var showAbstractLink = $('<a>').addClass('show-abstract-link').attr('href', '#').text('[show]').hide();

            // Add the new elements to the cell
            $(this).after(extendedAbstractSpan, shortenedAbstractSpan, showAbstractLink);

            var params = new URLSearchParams({
                doc_id: activeDocId,
                paper_id: paperId
            });

            var extendedAbstractReader = await apiCall('/get_extended_abstract?' + params.toString(), 'GET', {}, useFetch = true)
                .then(response => response.body.getReader());


            var decoder = new TextDecoder('utf-8');

            while (true) {
                var { value, done } = await extendedAbstractReader.read();
                if (done) {
                    break;
                }

                // Append the chunk to the extended abstract span
                var chunk = decoder.decode(value);
                extendedAbstractSpan.append(chunk);

                // Check if the shortened abstract span is empty
                if (!shortenedAbstractSpan.text()) {
                    // Fill the shortened abstract span with the first 100 characters of the extended abstract
                    shortenedAbstractSpan.text(extendedAbstractSpan.text().substr(0, 100) + '...');
                    showAbstractLink.show();
                }
            }

            // Change the button back to "Get Details" and make it enabled
            $(this).text('Get Details').prop('disabled', false);
            $(this).hide()
        });
    
    }
    
    function createAndPopulateTables(data) {
        // Create tables for References and Citations
        // DataTables is used for creating the tables

        var references = data['references'];
        var citations = data['citations'];
        
        createAndPopulateOneTable(references, '#references-table')
        createAndPopulateOneTable(citations, '#citations-table')
        
        
    }
    
    
    
    function loadCitationsAndReferences(){
        apiCall('/get_paper_details', 'GET', {doc_id: activeDocId}, useFetch = false)
        .done(function(data) {
                createAndPopulateTables(data);
            })
        .fail(function(jqXHR, textStatus, errorThrown) {
            // You can log all the parameters to see which one gives you the error message you're interested in.
            // 'jqXHR' is the full response object, 'textStatus' is a description of the type of error,
            // and 'errorThrown' is the textual portion of the HTTP status, such as "Not Found" or "Internal Server Error."
            alert(`An error occurred: ${textStatus}, ${errorThrown}`);
        })
    }
    
    
    
    function showPDF(pdfUrl) {
        var xhr = new XMLHttpRequest();
        var progressBar = document.getElementById('progressbar');
        var progressStatus = document.getElementById('progress-status');
        var viewer = document.getElementById('pdfjs-viewer');

        progressBar.style.width = '0%';
        progressStatus.textContent = '';
        viewer.style.display = 'none';  // Hide the viewer while loading
        document.getElementById('progress').style.display = 'block';  // Show the progress bar
        

        xhr.open('GET', '/proxy?file=' + encodeURIComponent(pdfUrl), true);
        xhr.responseType = 'blob';

        // Track progress
        xhr.onprogress = function(e) {
            document.getElementById('progress').style.display = 'block';
            if (e.lengthComputable) {
                var percentComplete = (e.loaded / e.total) * 100;
                progressStatus.style.display = 'block'; // Hide the progress status
                progressBar.style.display = 'block';
                progressBar.style.width = percentComplete + '%';
                progressStatus.textContent = 'Downloaded ' + (e.loaded / 1024).toFixed(2) + ' of ' + (e.total / 1024).toFixed(2) + ' KB (' + Math.round(percentComplete) + '%)';
            } else {
                progressStatus.style.display = 'block'; // Hide the progress status
                progressStatus.textContent = 'Downloaded ' + (e.loaded / 1024).toFixed(2) + ' KB';
            }
        }
        

        xhr.onload = function(e) {
            
            
            if (this.status == 200) {
                var blob = this.response;

                // Create an object URL for the Blob
                var objectUrl = URL.createObjectURL(blob);

                // Reset the src of the viewer
                viewer.setAttribute('src', viewer.getAttribute('data-original-src'));

                // Construct the full URL to the PDF
                var viewerUrl = viewer.getAttribute('src') + '?file=' + encodeURIComponent(objectUrl);

                // Load the PDF into the viewer
                viewer.setAttribute('src', viewerUrl);

                function resizePdfView(event) {
                    var width = $('#content-col').width();
                    var height = $("#pdf-questions").is(':hidden')? $(window).height() :$(window).height() * 0.8;
                    $('#pdf-content').css({
                        'width': width,
                    });
                    $(viewer).css({
                        'width': '100%',
                        'height': height,
                    });
                }

                $(window).resize(resizePdfView).trigger('resize'); // trigger resize event after showing the PDF

                viewer.style.display = 'block';  // Show the viewer once the PDF is ready
                document.getElementById('progress').style.display = 'none';  // Hide the progress bar
                progressStatus.style.display = 'none'; // Hide the progress status
                progressBar.style.display = 'none';
            } else {
                console.error("Error occurred while fetching PDF: " + this.status);
            }
        };

        xhr.send();
    }

    function toggleSidebar() {
        var sidebar = $('.sidebar');
        var sidebar = $('#doc-keys-sidebar');
        var contentCol = $('#content-col');
        var hideSidebarButton = $('#hide-sidebar');
        var showSidebarButton = $('#show-sidebar');

        if (sidebar.is(':visible')) {
            // If the sidebar is currently visible, hide it
            sidebar.addClass('d-none');
            hideSidebarButton.hide();
            showSidebarButton.show();

            // Adjust the width of the content column
            contentCol.removeClass('col-10').addClass('col-12');
        } else {
            // If the sidebar is currently hidden, show it
            sidebar.removeClass('d-none');
            hideSidebarButton.show();
            showSidebarButton.hide();

            // Adjust the width of the content column
            contentCol.removeClass('col-12').addClass('col-10');
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
    
    


    function setupViewDetailsView() {
        var view = $('#view-details-view');
        view.empty();
        
        if (activeDocId) {
            apiCall('/get_document_detail?doc_id=' + activeDocId, 'GET', {}).done(function(data) {
                view.empty();
                pdfUrl = data.source
                showPDF(data.source);
                
                view.append('<div id="details-row" class="row"></div>');

                var row = $('#details-row');

                var qnaExists = data.details.detailed_qna && data.details.detailed_qna.length > 0;
                var deepDetailsExists = data.details.deep_reader_details && Object.keys(data.details.deep_reader_details).length > 0;

                var summaryColClass = "col-12";

                row.append('<div id="summary-column" class="' + summaryColClass + '"></div>');

                if (qnaExists) {
                    view.append('<div id="qna-row" class="row"><div id="qna-column" class="col-12"></div></div>');
                }

                if (deepDetailsExists) {
                    view.append('<div id="deep-details-row" class="row"><div id="deep-details-column" class="col-12"></div></div>');
                }

                // Populate the summary column
                $('#summary-column').append('<h4>Summary</h4>');
                if (data.summary === '') {
                    $('#summary-column').append('<p id="summary-text"></p>');
                    $('#summary-column').append('<button id="get-summary-details-button" type="button" class="btn btn-primary">Generate Summary</button>');
                    $('#get-summary-details-button').click(async function() {
                        // The button element
                        const button = $(this);
                        // Disable the button during the fetch operation
                        button.prop('disabled', true);

                        // The paragraph element where the summary is displayed
                        
                        const paragraph = $('#summary-text');
                        paragraph.empty();

                        // Fetch the summary from the server
                        const response = await apiCall(`/streaming_summary?doc_id=${activeDocId}`, 'GET', {}, useFetch = true);

                        // Check if the HTTP response status is ok
                        if (!response.ok) {
                            alert('An error occurred: ' + response.status);
                            button.prop('disabled', false);  // Re-enable the button
                            return;
                        }

                        // Use the ReadableStream API to process the response
                        const reader = response.body.getReader();
                        const decoder = new TextDecoder();
                        accumulator = ''
                        final_text = ''
                        var content_length = 0
                        while (true) {
                            // Read a chunk of data from the stream
                            const { done, value } = await reader.read();

                            if (done) {
                                // The stream has ended
                                break;
                            }

                            // Decode the chunk and append it to the summary text
                            const chunk = decoder.decode(value);
                            // This hack of accumulator is only to ensure header tags are shown
                            let regex = /<\/?h[1-6][\s\S]*>/gi;
                            let close_regex = /<\/h[1-6]>/gi
                            let opening_regex = /<h[1-6][^>]*>/gi
                            if (!accumulator.includes('<h') || (opening_regex.test(accumulator) && close_regex.test(accumulator))){
                                paragraph.append(accumulator);
                                final_text = final_text + accumulator
                                accumulator = ''
                                if (paragraph.html().length > content_length + 40){
                                    renderInnerContentAsMarkdown(paragraph, 
                                                                 callback=null, continuous=true, html=final_text);
                                    content_length = paragraph.html().length
                                }
                            }
                            accumulator = accumulator + chunk;
                        }
                        paragraph.append(accumulator);
                        
                        // Replace the button with the summary text
                        button.replaceWith(paragraph);
                        
                        renderInnerContentAsMarkdown(paragraph, function(){
                            showMore(null, text=null, textElem=paragraph, as_html=true, show_at_start=true);
                        }, continuous=false, html=final_text);
                    });

                } else {
                    $('#summary-column').append('<p id="summary-text">' + data.summary.replace(/\n/g, '  \n') + '</p>');
                    renderInnerContentAsMarkdown($('#summary-text'), function(){
                        showMore(null, text=null, textElem=$('#summary-text'), as_html=true);
                    }, continuous=false, html=data.summary.replace(/\n/g, '  \n'));
                    
                }

                
                var chunkContainer = $('<div class="summary-text"></div>')
                chunked_summary = data.details.chunked_summary;

                for (var i = 0; i < chunked_summary.length; i++) {
                    // $('#summary-column').append('<h5>' + titles[i] + '</h5>');
                    chunkContainer.append('<p>' + data.details.chunked_summary[i].replace(/\n/g, '  \n') + '</p></br>');
                }
                if (chunked_summary.length > 0 && chunked_summary[0].length > 0) {
                    $('#summary-column').append(chunkContainer)
                    renderInnerContentAsMarkdown(chunkContainer, function(){
                        showMore(null, text=null, textElem=chunkContainer, as_html=true);
                    }, continuous=false, html=chunked_summary.join('\n\n').replace(/\n/g, '  \n'));
                }
                
                // Populate the QnA column if exists
                if (qnaExists) {
                    $('#qna-column').append('<h4>Questions and Answers</h4>');
                   
                    data.details.detailed_qna.forEach(function(one_qa) {
                        let card = $('<div>').addClass('card').attr("content-id", one_qa[0]);
                        let cardBody = $('<div>').addClass('card-body');
                        card.append(cardBody);
                        cardBody.append('<p><strong>Q:</strong> ' + one_qa[1].replace(/\n/g, '  \n') + '</p>');
                        var ansArea = $('<p><strong>A:</strong></p>')
                        var ansContainer = $('<span class = "summary-text">' + one_qa[2].replace(/\n/g, '  \n') +'</span>')
                        ansArea.append(ansContainer)
                        cardBody.append(ansArea);
                        $('#qna-column').append(card);
                        initialiseVoteBank(card, one_qa[1], one_qa[0], activeDocId=activeDocId);
                        renderInnerContentAsMarkdown(ansContainer, function(){
                            showMore(null, text=null, textElem=ansContainer, as_html=true);
                        }, continuous=false, html=one_qa[2].replace(/\n/g, '  \n'));
                        
                    });
                    
                }

                // Populate the deep details column if exists
                if (deepDetailsExists) {
                    $('#deep-details-column').append('<h4>More Details</h4>');

                    // Define the order of keys
                    var keyOrder = [
                        "methodology",
                        "previous_literature_and_differentiation",
                        "experiments_and_evaluation",
                        "results_and_comparison",
                        "limitations_and_future_work"
                    ];

                    keyOrder.forEach(function(key) {
                        if (data.details.deep_reader_details.hasOwnProperty(key)) {
                            let card = $('<div>').addClass('card').attr("content-id", data.details.deep_reader_details[key]["id"]);
                            let cardBody = $('<div>').addClass('card-body');
                            card.append(cardBody);
                            cardBody.append('<h5>' + key.replace(/_/g, ' ') + '</h5>');
                            cardBody.append(`<p class="summary-text" id="${key}-text">` + data.details.deep_reader_details[key]["text"] + '</p>');
                            $('#deep-details-column').append(card);
                            initialiseVoteBank(card, key, data.details.deep_reader_details[key]["id"], activeDocId=activeDocId);
                            renderInnerContentAsMarkdown($(`#${key}-text`), function(){
                                if (data.details.deep_reader_details[key]["text"].trim().length > 0){
                                    showMore(null, text=null, textElem=$(`#${key}-text`), as_html=true);
                                }
                            }, continuous=false, html=data.details.deep_reader_details[key]["text"]);
                            
                            if (data.details.deep_reader_details[key]["text"] === '') {
                                cardBody.append('<button id="get-details-' + key + '-button" type="button" class="btn btn-primary">Get Details</button>');
                                $('#get-details-' + key + '-button').click(async function() {
                                    // Put your API call here
                                    var url = "/get_fixed_details?doc_id=" + activeDocId + "&detail_key=" + key;
                                    const response = await apiCall(url, 'GET', {}, useFetch = true);
                                    if(!response.ok) {
                                        alert('An error occurred: ' + response.status);
                                        return;
                                    }

                                    $('#get-details-' + key + '-button').prop('disabled', true); // Disable the button
                                    var content_length = 0
                                    let reader = response.body.getReader();
                                    let decoder = new TextDecoder();
                                    final_text = ''
                                    while (true) {
                                        let { value, done } = await reader.read();
                                        if (done) {
                                            break;
                                        }
                                        let part = decoder.decode(value).replace(/\n/g, '  \n');
                                        $('#' + key + '-text').append(part);
                                        final_text += part
                                        if ($('#' + key + '-text').html().length > content_length + 40){
                                            renderInnerContentAsMarkdown($('#' + key + '-text'), 
                                                                         callback=null, continuous=true, html=final_text)
                                            content_length = $('#' + key + '-text').html().length
                                        }
                                    }
                                    renderInnerContentAsMarkdown($('#' + key + '-text'), function(){
                                        showMore(null, text=null, textElem=$('#' + key + '-text'), 
                                                 as_html=true, show_at_start=true);
                                    }, continuous=false, html=final_text);
                                    $('#get-details-' + key + '-button').remove(); // Remove the button
                                });
                            }
                        }
                    });
                    
                }
            });
        }
    }
    
    function deleteDocument(docId) {
         if (!confirm('Are you sure you want to delete this document?')) {
            return;
        }
        apiCall('/delete_document?doc_id=' + docId, 'DELETE', {}, useFetch = false)
        .done(function(result) {
                // Remove document from the sidebar
                $('#documents .list-group-item[data-doc-id="' + docId + '"]').remove();

                // If the deleted document was the active one, deselect it and clear the views
                if (docId === activeDocId) {
                    activeDocId = null;
                    localStorage.setItem('activeDocId', activeDocId);
                    pdfUrl = null;
                    $('.view').empty();
                }

                // Reload the list of documents and select a new active document if necessary
                loadDocuments();
            })
        .fail(function(request, status, error) {
                alert('Failed to delete document: ' + error);
            });
    }


    function loadDocuments(autoselect=true, search_term='') {
        if (search_term.length > 0) {
            api = '/search_document?text='+ search_term
            search_mode = true
        } else {
            api = '/list_all'
            search_mode = false
        }
        var request = apiCall(api, 'GET', {})
        request.done(function(data) {
            // Auto-select the first document
            var firstDoc = true;
            $('#documents').empty();
            data.forEach(function(doc) {
                var docItem = $('<a href="#" class="list-group-item list-group-item-action" data-doc-id="' + doc.doc_id + '"></a>');
                var deleteButton = $('<small><button class="btn p-0 ms-2 delete-button"><i class="bi bi-trash-fill"></i></button></small>');
                docItem.append('<strong class="doc-title-in-sidebar">' + doc.title.slice(0, 60).trim() + '</strong></br>');
                docItem.append(deleteButton);
                docItem.append('&nbsp; &nbsp; <span>' + '<a class="sidebar-source-link" href="' + doc.source +'">' + "Link" + '</a>' + '</span></br>');
                // Append delete button to docItem
                
                showMore(docItem, doc.short_summary.replace(/\n/g, '<br>'))
                $('#documents').append(docItem);
                
                if (autoselect){
                    if (firstDoc) {
                        setActiveDoc(activeDocId|| doc.doc_id);
                        firstDoc = false;
                    }
                }

            });
            if (!search_mode) {
                highLightActiveDoc();
            }
            // Handle click events for the delete button
            $('.delete-button').click(function(event) {
                event.preventDefault();
                event.stopPropagation();
                var docId = $(this).closest('[data-doc-id]').attr('data-doc-id');
                deleteDocument(docId);
            });


            
        });
        return request
    }
    

    function initSearch(searchBoxId){
        var lastTimeoutId = null;  // Store the timeout id
        var previousSearchLength = 0;  // Stores the previous search length to check for delete action
        var searchBox = $('#' + searchBoxId);

        searchBox.on('input', function() {
            var currentSearchLength = searchBox.val().length;

            // Clear the previously scheduled search
            if (lastTimeoutId !== null) {
                clearTimeout(lastTimeoutId);
            }

            // Schedule a new search
            lastTimeoutId = setTimeout(function() {
                currentSearchLength = searchBox.val().length;
                if (currentSearchLength >= 5 || (previousSearchLength >= 5 && currentSearchLength < 5)) {  
                    loadDocuments(true, searchBox.val());
                } else if (currentSearchLength === 0 && previousSearchLength >= 1) {
                    loadDocuments(true, '');
                }
                previousSearchLength = currentSearchLength;  // Update the previous search length for next check
                
                
                lastTimeoutId = null;  // Reset the timeout id since the search has been completed
            }, 400);
        });
    }
    



    
    function removeAskQuestionView(){
        $('#question-input').remove();
        $('#submit-question-button').remove();
        $('#loading').remove();
        $('#answers').remove();
        removeOptions('questions-view', 'query');
    }

    function setupAskQuestionsView() {
        if ($('#questions-view').length === 0) {
            var view = $('<div id="questions-view"></div>');
            $('#ask-questions-view').append(view)
        } else {
            var view = $('#questions-view')
        }
        removeAskQuestionView();
        view.append('<div id="answers" class="card mt-2" style="display:none;"></div>');  // Applying bootstrap card class
        view.append('<input id="question-input" type="text" placeholder="Ask a question...">');
        view.append('<button id="submit-question-button" type="button">Submit Question</button>');
        view.append('<div id="loading" style="display:none;"><div class="spinner-border text-primary" role="status"><span class="sr-only">Loading...</span></div></div>');
        addOptions('questions-view', 'query', activeDocId);

        async function askQuestion() {
            $("#answers").removeAttr('style')
            var query = $('#question-input').val();
            if (query && query.trim() !== '') {
                removeFollowUpView();

                $('#question-input').prop('disabled', true);
                $('#submit-question-button').prop('disabled', true);
                $('#loading').show();
                let options = getOptions('questions-view', 'query');
                let response = await apiCall('/streaming_get_answer', 'POST', { doc_id: activeDocId, query: query, ...options}, useFetch = true);
                if (!response.ok) {
                    alert('An error occurred: ' + response.status);
                    return;
                }

                let reader = response.body.getReader();
                let decoder = new TextDecoder();

                let card = $('<div>').addClass('card');
                let cardBody = $('<div>').addClass('card-body');
                card.append(cardBody);
                cardBody.append('<h5 class="card-title">Question:</h5>');
                cardBody.append('<p class="card-text">'+query+'</p>');
                cardBody.append('<h5 class="card-title">Answer:</h5>');
                let answerParagraph = $('<p>').addClass('card-text').addClass('summary-text').attr('id', 'main-answer-paragraph');
                cardBody.append(answerParagraph);

                $('#answers').append(card);
                

                answer = "";
                var content_length = 0
                while (true) {
                    let { value, done } = await reader.read();
                    if (done) {
                        break;
                    }
                    let part = decoder.decode(value);
                    answerParagraph.append(part);
                    answer = answer + part;
                    if (answerParagraph.html().length > content_length + 40){
                        renderInnerContentAsMarkdown(answerParagraph, 
                                                     callback=null, continuous=true, html=answer);
                        content_length = answerParagraph.html().length
                    }
                }
                renderInnerContentAsMarkdown(answerParagraph, function(){
                    showMore(null, text=null, textElem=answerParagraph, as_html=true, show_at_start=true);
                }, continuous=false, html=answer);
                initialiseVoteBank(card, query, activeDocId=activeDocId);

                answerParagraph.append('</br>');
                resetOptions('questions-view', 'query');
                setupFollowUpQuestionView({"query": query, "answer": answer});

                $('#question-input').prop('disabled', false);
                $('#submit-question-button').prop('disabled', false);
                $('#loading').hide();
            }
        }


        $('#submit-question-button').click(askQuestion);

        $('#question-input').keypress(function(e) { // Add this block to submit the question on enter
            if (e.which == 13 && !e.shiftKey && !e.altKey) {
                askQuestion();
                return false; // Prevents the default action
            }
            if ((e.keyCode == 13 && e.altKey) || (e.keyCode == 13 && e.shiftKey)) {
                addNewlineToTextbox('question-input');
                
                return false; // Prevents the default action
            }

        });
    }


    function removeFollowUpView(){
        $('#follow-up-question-input').remove();
        $('#submit-follow-up-question-button').remove();
        $('#loading-follow-up').remove();
        removeOptions('followup-view', 'followup');
    }

    function setupFollowUpQuestionView(previousAnswer) {
        if ($('#followup-view').length === 0) {
            var view = $('<div id="followup-view"></div>');
            $('#ask-questions-view').append(view)
        } else {
            var view = $('#followup-view')
        }
        removeFollowUpView();

        view.append('<input id="follow-up-question-input" type="text" placeholder="Ask a follow-up question...">');
        view.append('<button id="submit-follow-up-question-button" type="button">Submit Follow-Up Question</button>');
        addOptions('followup-view', 'followup', activeDocId);
        view.append('<div id="loading-follow-up" style="display:none;"><div class="spinner-border text-primary" role="status"><span class="sr-only">Loading...</span></div></div>');

        async function askFollowUpQuestion() {
            var query = $('#follow-up-question-input').val();
            if (query && query.trim() !== '') {
                $('#follow-up-question-input').prop('disabled', true); // Disable the input box
                $('#submit-follow-up-question-button').prop('disabled', true); // Disable the submit button
                $('#loading-follow-up').show(); // Show the loading spinner
                let options = getOptions('followup-view', 'followup');
                let response = await apiCall('/streaming_get_followup_answer', 'POST', { doc_id: activeDocId, query: query, previous_answer: previousAnswer, ...options}, useFetch = true);
                if (!response.ok) {
                    alert('An error occurred: ' + response.status);
                    return;
                }

                let reader = response.body.getReader();
                let decoder = new TextDecoder();

                let card = $('<div>').addClass('card');
                let cardBody = $('<div>').addClass('card-body');
                card.append(cardBody);
                cardBody.append('<h5 class="card-title">Follow-Up Question:</h5>');
                cardBody.append('<p class="card-text">'+query+'</p>');
                cardBody.append('<h5 class="card-title">Follow-Up Answer:</h5>');
                let answerParagraph = $('<p>').addClass('card-text').attr('id', 'followup-answer-paragraph');
                cardBody.append(answerParagraph);

                $('#answers').append(card);
                
                var content_length = 0
                answer = ""
                while (true) {
                    let { value, done } = await reader.read();
                    if (done) {
                        break;
                    }
                    let part = decoder.decode(value).replace(/\n/g, '  \n');
                    answerParagraph.append(part);
                    answer = answer + part
                    if (answerParagraph.html().length > content_length + 40){
                        renderInnerContentAsMarkdown(answerParagraph, 
                                                     callback=null, continuous=true, html=answer);
                        content_length = answerParagraph.html().length
                    }
                }
                renderInnerContentAsMarkdown(answerParagraph, function(){
                    showMore(null, text=null, textElem=answerParagraph, as_html=true, show_at_start=true);
                }, continuous=false, html=answer);
                initialiseVoteBank(card, previousAnswer["query"]+ ". followup:" +query, activeDocId=activeDocId);

                answerParagraph.append('</br>');

                $('#follow-up-question-input').prop('disabled', false); // Re-enable the input box
                $('#submit-follow-up-question-button').prop('disabled', false); // Re-enable the submit button
                $('#loading-follow-up').hide(); // Hide the loading spinner
                resetOptions('followup-view', 'followup');
                setupFollowUpQuestionView(JSON.stringify({ doc_id: activeDocId, query: query, previous_answer: previousAnswer, answer:answer}));
            }
        }

        $('#submit-follow-up-question-button').click(askFollowUpQuestion);

        $('#follow-up-question-input').keypress(function(e) { // Add this block to submit the question on enter
            if (e.which == 13 && !e.shiftKey && !e.altKey) {
                askFollowUpQuestion();
                return false; // Prevents the default action
            }
            if ((e.keyCode == 13 && e.altKey)||(e.keyCode == 13 && e.shiftKey)) {
                addNewlineToTextbox('follow-up-question-input');
                
                return false; // Prevents the default action
            }
        });
    }


    function highLightActiveDoc(){
        $('#documents .list-group-item').removeClass('active');
        $('#documents .list-group-item[data-doc-id="' + activeDocId + '"]').addClass('active');
    }

    function setActiveDoc(docId) {
        activeDocId = docId;
        localStorage.setItem('activeDocId', activeDocId);
        loadCitationsAndReferences();
        setupReviewTab();
        highLightActiveDoc();
        setupAskQuestionsView();
        setupViewDetailsView();
    }

    function setupPDFModalSubmit() {
        let doc_modal = $('#add-document-modal');
        $('#add-document-button').off().click(function() {
            $('#add-document-modal').modal({backdrop: 'static', keyboard: false}, 'show');
        });
        function success(response) {
            doc_modal.find('#submit-button').prop('disabled', false);  // Re-enable the submit button
            doc_modal.find('#submit-spinner').hide();  // Hide the spinner
            if (response.status) {
                alert(JSON.stringify(response));
                var newDocId = response.doc_id;
                // refresh the document list
                loadDocuments(false)
                    .done(function(){
                        doc_modal.modal('hide');
                        setActiveDoc(newDocId);
                    })
                    .fail(function(){
                        doc_modal.modal('hide');
                        alert(response.error);
                    })
                // set the new document as the current document
                
            } else {
                alert(response.error);
                doc_modal.modal('hide');
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
            fetch('/upload_pdf', { 
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
            // check for doc and docx
            if (file && (file.type === 'application/pdf' || file.type === 'application/msword' || file.type === 'application/vnd.openxmlformats-officedocument.wordprocessingml.document')) {
                uploadFile(file);  // Call the file upload function
            }
        });
    
        let dropArea = doc_modal.find('#drop-area');
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
                    // If the dropped item is a file and it's a PDF
                    // check if it is a doc or docx
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
                apiCall('/index_document', 'POST', { pdf_url: pdfUrl }, useFetch = false)
                    .done(success)
                    .fail(failure);
            } else {
                alert('Please enter a PDF URL');
            }
        });
    }

    function setupReviewTab() {
        $('#show_reviews').empty();
        $('#write_review').empty();

        $('#write_review').append(`
            <form id="review_form">
                <div class="form-row">
                    <div class="form-group col-md-6">
                        <label for="review_params">Review Parameters</label>
                        <select class="form-control" id="review_params">
                            <!-- Options to be populated dynamically -->
                        </select>
                    </div>
                    <div class="form-group col-md-6">
                        <label for="sub_review_params">Sub Review Parameters</label>
                        <select class="form-control" id="sub_review_params" disabled>
                            <!-- Options to be populated dynamically -->
                        </select>
                    </div>
                </div>
                <div class="form-group">
                    <label for="additional_instructions">Additional Instructions</label>
                    <textarea class="form-control" id="additional_instructions" rows="3"></textarea>
                </div>
                <div class="form-row">
                    <div class="form-group col-md-6">
                        <label for="tone">Tone</label>
                        <div id="tone" class="d-flex">
                            <!-- Radio buttons to be populated dynamically -->
                        </div>
                    </div>
                    <div class="form-group col-md-6 d-flex align-items-end">
                        <div class="form-check mr-3">
                            <input type="checkbox" class="form-check-input" id="score_this_review">
                            <label class="form-check-label" for="score_this_review">Score this Review</label>
                        </div>
                        
                    </div>
                </div>
                <button type="submit" class="btn btn-primary">Submit</button>
            </form>
        `)

        var unused_var = `
                        <div class="form-check mr-3">
                            <input type="checkbox" class="form-check-input" id="use_previous_reviews">
                            <label class="form-check-label" for="use_previous_reviews">Use Previous Reviews</label>
                        </div>
                        <div class="form-check">
                            <input type="checkbox" class="form-check-input" id="is_meta_review">
                            <label class="form-check-label" for="is_meta_review">Is Meta Review</label>
                        </div>
        `

        if (activeDocId === null || activeDocId === undefined) {
            return;
        }

        var tones = ["positive", "negative", "neutral", "none"];
        var doc_id = activeDocId; // replace with your doc id

        $.get('/get_reviews/' + doc_id, function(data) {
            // populate reviews in cards
            $.each(data.reviews, function(idx, review) {
                var card = $('<div>').addClass('card');
                var cardBody = $('<div>').addClass('card-body');
                card.append(cardBody);
                cardBody.append(`<h5 class="card-title">${review.header}</h5>`);
                cardBody.append('<p class="card-text">'+review.description+'</p>');
                cardBody.append('<h5 class="card-title">Additional Instructions:</h5>');
                cardBody.append('<p class="card-text">'+review.instructions+'</p>');
                cardBody.append('<h5 class="card-title">Tone:</h5>');
                cardBody.append('<p class="card-text">'+review.tone+'</p>');
                cardBody.append('<h5 class="card-title">Meta Review:</h5>');
                cardBody.append('<p class="card-text">'+review.is_meta_review+'</p>');
                cardBody.append('<h5 class="card-title">Review:</h5>');
                let reviewParagraph = $('<p>').addClass('card-text').attr('id', 'main-review-paragraph');
                cardBody.append(reviewParagraph);
                reviewParagraph.append(review.review);
                $('#show_reviews').append(card);
                renderInnerContentAsMarkdown(reviewParagraph, function(){
                    showMore(null, text=null, textElem=reviewParagraph, as_html=true, show_at_start=true);
                }, continuous=false, html=review.review);
                initialiseVoteBank(card, [review.tone,review.review_topic, review.instructions, review.is_meta_review].join(","), review.id), activeDocId=activeDocId;

            });
            // populate review parameters dropdown
            $.each(data.review_params, function(key, value) {
                var new_opt = $("<option></option>").attr("value", key).text(key)
                $('#review_params').append(new_opt);
                if (!$.isArray(value)) {
                    new_opt.attr("description", value)
                }
            })
            $('#review_params').trigger('change');

            // populate tone radio buttons
            $.each(tones, function(index, tone) {
                var radioItem = `
                <div class="form-check form-check-inline">
                    <div class="input-container">
                        <input class="form-check-input" type="radio" name="tone" id="${tone}" value="${tone}">
                    </div>
                    <label class="form-check-label" for="${tone}">
                      ${tone}
                    </label>
                </div>
                `;
                $('#tone').append(radioItem);
            });
        });

        // update sub review parameters dropdown when review parameters selection changes
        $('#review_params').change(function() {
            var selected_param = $(this).val();

            $.get('/get_reviews/' + doc_id, function(data) {
                var sub_params = data.review_params[selected_param];

                if ($.isArray(sub_params)) {
                    $('#sub_review_params').empty().prop('disabled', false);
                    
                    $.each(sub_params, function(index, value) {
                        $('#sub_review_params').append($("<option></option>").attr("value", index).attr("description", value[1]).text(value[0]));
                    });
                } else {
                    $('#sub_review_params').empty().prop('disabled', true);
                }
            });
        });
        

        $('#review_form').submit(async function(e) {
            e.preventDefault();
            var selectedOption = $('#review_params').find('option:selected')
            var header = selectedOption.text()
            var header_description = selectedOption.attr("description")

            var subSelectedOption = $('#sub_review_params').find('option:selected')
            var sub_header = subSelectedOption.text()
            var sub_description = subSelectedOption.attr("description")

            var review_topic = $('#review_params').val() + "," + $('#sub_review_params').val();
            var tone = $("input[name='tone']:checked").val();
            var additional_instructions = $('#additional_instructions').val();
            var score_this_review = $('#score_this_review').is(":checked") ? 1 : 0;
            // var use_previous_reviews = $('#use_previous_reviews').is(":checked") ? 1 : 0;
            var use_previous_reviews = 0
            // var is_meta_review = $('#is_meta_review').is(":checked") ? 1 : 0;
            var is_meta_review = 0
        
            var write_review_url = '/write_review/' + doc_id + '/' + tone +
                '?review_topic=' + review_topic +
                '&instruction=' + additional_instructions +
                '&score_this_review=' + score_this_review +
                '&use_previous_reviews=' + use_previous_reviews +
                '&is_meta_review=' + is_meta_review;
        
            
            let card = $('<div>').addClass('card').addClass('review-card');
            let cardBody = $('<div>').addClass('card-body');
            card.append(cardBody);
            var cardHeader = $(`
                <div><h5 class="card-title">Review Parameters:</h5></div>
            `)
            cardHeader.append('<p class="card-text">'+`<b>${header}</b>`+'</p>');
            if (header_description != null){
                cardHeader.append('<p class="card-text">'+`${header_description}`+'</p>');
            }

            cardHeader.append('<p class="card-text">'+`<b>${sub_header}</b>`+'</p>');
            if (sub_description != null){
                cardHeader.append('<p class="card-text">'+`${sub_description}`+'</p>');
            }
            
            if (additional_instructions.length > 0){
                cardHeader.append('<h5 class="card-title">Additional Instructions:</h5>');
                cardHeader.append('<p class="card-text">'+additional_instructions+'</p>');
            }
            cardHeader.append('<p class="card-text">Tone = '+tone+'</p>');
            cardHeader.append('<h5 class="card-title">Review:</h5>');
            cardBody.append(cardHeader);

            let spinner = $('<div class="spinner-border text-primary" role="status" id="review-loading-spinner">').css('display', 'none');
            let spinnerText = $('<span class="sr-only">Loading...</span>');
            spinner.append(spinnerText);
            cardBody.append(spinner);

            let reviewParagraph = $('<p>').addClass('card-text').attr('id', 'main-review-paragraph');
            cardBody.append(reviewParagraph);
            
            let first_review_card = $('.review-card:first');
            if (first_review_card.length > 0){
                first_review_card.before(card);
            } else {
                $('#write_review').append(card);
            }
            $('#review-loading-spinner').css('display', 'block');
            let response = await fetch(write_review_url);
            responseWaitAndSuccessChecker(write_review_url, response);
            renderInnerContentAsMarkdown(cardHeader, function(){
                showMore(null, text=null, textElem=cardHeader, as_html=true, show_at_start=true);
            });
            let reader = response.body.getReader();
            let decoder = new TextDecoder();
            let review = "";
            var content_length = 0;
            while (true) {
                let { value, done } = await reader.read();
                if (done) {
                    $('#review-loading-spinner').css('display', 'none');
                    break;
                } else {
                    $('#review-loading-spinner').css('display', 'block');
                }
                let part = decoder.decode(value);
                reviewParagraph.append(part);
                review = review + part;
                if (reviewParagraph.html().length > content_length + 40){
                    renderInnerContentAsMarkdown(reviewParagraph, 
                                                    callback=null, continuous=true, html=review);
                    content_length = reviewParagraph.html().length
                }
            }
            renderInnerContentAsMarkdown(reviewParagraph, function(){
                showMore(null, text=null, textElem=reviewParagraph, as_html=true, show_at_start=true);
            }, continuous=false, html=review);
            initialiseVoteBank(card, [tone,review_topic, additional_instructions, is_meta_review].join(","), activeDocId=activeDocId);
        });



    }

    
    initialiseKeyStore();
    showUserName();
    loadDocuments();
    initSearch("searchBox");
    setupAskQuestionsView();
    setupPDFModalSubmit();
    initiliseNavbarHiding();
    
    $('#refresh-references, #refresh-citations').on('click', function() {
        apiCall('/refetch_paper_details', 'GET', {doc_id: activeDocId}, useFetch = false)
        .done(function(data) {
                createAndPopulateTables(data);
            })
        .fail(function(jqXHR, textStatus, errorThrown) {
            // You can log all the parameters to see which one gives you the error message you're interested in.
            // 'jqXHR' is the full response object, 'textStatus' is a description of the type of error,
            // and 'errorThrown' is the textual portion of the HTTP status, such as "Not Found" or "Internal Server Error."
            alert(`An error occurred: ${textStatus}, ${errorThrown}`);
        })
    });
    
    $('#details-tab').on('shown.bs.tab', function (e) {
        // Call the '/get_paper_details' API to fetch the data
        $('#pdf-view').hide();
        $('#review-assistant-view').hide();
        $('#references-view').show();
        $('#chat-assistant-view').hide();

        loadCitationsAndReferences();
        pdfTabIsActive();
    });

    $('#review-assistant-tab').on('shown.bs.tab', function (e) {
        // Call the '/get_paper_details' API to fetch the data
        $('#pdf-view').hide();
        $('#references-view').hide();
        $('#review-assistant-view').show();
        $('#chat-assistant-view').hide();
        pdfTabIsActive();
        var sidebar = $('.sidebar');
        if (!sidebar.is(':visible')) {
            toggleSidebar();
        }
        
    });
    
    $('#pdf-tab').on('shown.bs.tab', function (e) {
        // Clear the details viewer
        $('#review-assistant-view').hide();
        $('#references-view').hide();
        $('#pdf-view').show();
        $('#chat-assistant-view').hide();
        pdfTabIsActive();
        var sidebar = $('.sidebar');
        if (!sidebar.is(':visible')) {
            toggleSidebar();
        }
        
    });

    $('#assistant-tab').on('shown.bs.tab', function (e) {
        // Clear the details viewer
        loadConversations();
        $('#review-assistant-view').hide();
        $('#references-view').hide();
        $('#pdf-view').hide();
        $('#chat-assistant-view').show();
        var chatView = $('#chatView');
        chatView.scrollTop(chatView.prop('scrollHeight'));
        $('#messageText').focus();
        pdfTabIsActive();
        var sidebar = $('.sidebar');
        if (sidebar.is(':visible')) {
            toggleSidebar();
        }

    });
    
    $('#hide-sidebar').on('click', toggleSidebar);
    $('#show-sidebar').on('click', toggleSidebar);
    
    document.getElementById('toggle-tab-content').addEventListener('click', function() {
        var tabContent = $("#pdf-view").find("#pdfjs-viewer")[0];
        if (tabContent.style.display === 'none') {
            tabContent.style.display = 'block';
        } else {
            tabContent.style.display = 'none';
        }
    });

    document.getElementById('pdf-tab').addEventListener('click', function() {
        var tabContent = document.querySelector('.tab-content');
        tabContent.style.display = 'block';
    });

    document.getElementById('details-tab').addEventListener('click', function() {
        var tabContent = document.querySelector('.tab-content');
        tabContent.style.display = 'block';
    });

    document.getElementById('review-assistant-tab').addEventListener('click', function() {
        var tabContent = document.querySelector('.tab-content');
        tabContent.style.display = 'block';
    });

    $(document).on('click', '.copy-code-btn', function() {
        copyToClipboard($(this), "code");
    });
    hljs.initHighlightingOnLoad();


    $('#toggle-tab-content').on('click', function() {
        var caretUp = $(this).find('.bi-caret-up-fill');
        var caretDown = $(this).find('.bi-caret-down-fill');

        if (caretUp.is(':visible')) {
            caretUp.hide();
            caretDown.show();
        } else {
            caretDown.hide();
            caretUp.show();
        }
    });

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
    $('#review-assistant-view').hide();
    $('#references-view').hide();
    $('#pdf-view').show();

    $("#hide-navbar").parent().hide(); // Hide the Show only PDF button
    $("#details-tab").parent().hide(); // Hide the Cites and Refs tab
    $("#toggle-tab-content").parent().hide();

    // Listen for click events on the tabs
    $(".nav-link").click(function() {
        // Check if the PDF tab is active
        pdfTabIsActive();
    });

    function pdfTabIsActive() {
        if ($("#pdf-tab").hasClass("active")) {
            // If it is, show the elements
            $("#hide-navbar").parent().show();
            $("#toggle-tab-content").parent().show();
            $("#details-tab").parent().show();
        } else {
            // If it's not, hide the elements
            $("#hide-navbar").parent().hide();
            $("#toggle-tab-content").parent().hide();
            $("#details-tab").parent().hide();
        }
    }
    $('#assistant-tab').trigger('shown.bs.tab');
    $("a#assistant-tab.nav-link").addClass('active');
    $("a#pdf-tab.nav-link").removeClass('active');
    pdfTabIsActive();
    // $("#assistant-tab").tigger('click');
    // $("a#assistant-tab.nav-link").trigger('click');

});
