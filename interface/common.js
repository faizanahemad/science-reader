var currentDomain = {
    domain: 'assistant', // finchat, search
}

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
function setMaxHeightForTextbox(textboxId, height = 10) {
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

function showMore(parentElem, text = null, textElem = null, as_html = false, show_at_start = false) {

    if (textElem) {

        if (as_html) {
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
        moreText.find('.show-more').each(function () { $(this).remove(); })
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
        if (moreText) {
            var lessText = text.slice(0, 20);
            textElem.append(lessText + '<span class="more-text" style="display:none;">' + moreText + '</span>' + ' <a href="#" class="show-more">[show]</a>');
        } else {
            textElem.append(text);
        }
    }

    if (parentElem) {
        parentElem.append(textElem);
    }

    function toggle(event) {
        if (event) {
            event.preventDefault();
            event.stopPropagation();
        }
        var moreText = textElem.find('.more-text');
        var lessText = textElem.find('.less-text');
        if (moreText.is(':visible')) {
            moreText.hide();
            if (lessText) {
                lessText.show()
            }
            textElem.find('.show-more').each(function () { $(this).text('[show]'); })
            $(this).text('[show]');
        } else {
            moreText.show();
            if (lessText) {
                lessText.hide()
            }
            textElem.find('.show-more').each(function () { $(this).text('[hide]'); })
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

function initialiseVoteBank(cardElem, text, contentId = null, activeDocId = null, disable_voting = false) {
    let voteCountElem = $('<p>').addClass('vote-count');
    let upvoteBtn = $('<button>').addClass('vote-btn').addClass('upvote-btn').text('👍');
    let downvoteBtn = $('<button>').addClass('vote-btn').addClass('downvote-btn').text('👎');
    let copyBtn = $('<button>').addClass('vote-btn').addClass('copy-btn').text('📋');
    copyBtn.click(function () {
        // Here we get the card text and copy it to the clipboard
        // let cardText = cardElem.text().replace(/\[show\]|\[hide\]/g, '');
        copyToClipboard(cardElem, text);
    });

    let voteBox = $('<div>').addClass('vote-box').css({
        'position': 'absolute',
        'top': '5px',
        'right': '30px'
    });
    if (disable_voting) {
        voteBox.append(copyBtn);
        cardElem.append(voteBox);
        return
    }
    voteBox.append(copyBtn, upvoteBtn, voteCountElem, downvoteBtn);
    cardElem.append(voteBox);

    function updateVoteCount() {
        var request = $.ajax({
            url: '/getUpvotesDownvotesByQuestionId/' + contentId,
            type: 'POST',
            data: JSON.stringify({ doc_id: activeDocId, question_text: text, question_id: contentId }),
            dataType: 'json',
            contentType: 'application/json',
        });



        request.done(function (data) {
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
            function (data) {
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
            data: JSON.stringify({ doc_id: activeDocId, question_text: text, question_id: contentId }),
            dataType: 'json',
            contentType: 'application/json',
        });

        request.done(function (data) {
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
        let checkedValues = $(modalID + ' input[type=checkbox]:checked').map(function () {
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
        apiCall('/addUserQuestionFeedback', 'POST', feedbackData).always(function () {
            // After the feedback is successfully submitted, clear the checkboxes and textarea
            $(modalID + ' input[type=checkbox]').prop('checked', false);
            $(modalID + ' textarea').val('');
        });;
    }

    upvoteBtn.click(function () {
        apiCall('/addUpvoteOrDownvote', 'POST', { question_id: contentId, doc_id: activeDocId, upvote: 1, downvote: 0, question_text: text }).done(function () {
            upvoteBtn.addClass('voted');
            downvoteBtn.removeClass('voted');
            updateVoteCount();
            checkUserVote();

            $('#positive-feedback-modal').modal('show');
            $('.submit-positive-feedback').off('click').click(function () {
                sendFeedback('positive');
            });
        });

    });

    downvoteBtn.click(function () {
        apiCall('/addUpvoteOrDownvote', 'POST', { question_id: contentId, doc_id: activeDocId, upvote: 0, downvote: 1, question_text: text }).done(function () {
            upvoteBtn.addClass('voted');
            downvoteBtn.removeClass('voted');
            updateVoteCount();
            checkUserVote();

            $('#negative-feedback-modal').modal('show');
            $('.submit-negative-feedback').off('click').click(function () {
                sendFeedback('negative');
            });
        });
    });
    setTimeout(function () {
        updateVoteCount();
        checkUserVote();
    }, 8000);
}
const markdownParser = new marked.Renderer();
marked.setOptions({
    renderer: markdownParser,
    highlight: function (code, language) {
        const validLanguage = hljs.getLanguage(language) ? language : 'plaintext';
        if (validLanguage === 'plaintext') {
            return hljs.highlightAuto(validLanguage, code).value;
        }
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
markdownParser.codespan = function (text) {
    return '<code>' + text + '</code>';
};
markdownParser.code = function (code, language) {
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


function renderInnerContentAsMarkdown(jqelem, callback = null, continuous = false, html = null) {
    parent = jqelem.parent()
    elem_id = jqelem.attr('id');
    elem_to_render_in = jqelem
    brother_elem_id = elem_id + "-md-render"
    if (continuous) {
        brother_elem = parent.find('#' + brother_elem_id);
        if (!brother_elem.length) {
            var brother_elem = $('<p/>', { id: brother_elem_id })
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

    if (html == null) {
        try {
            html = jqelem.html()
        } catch (error) {
            try { html = jqelem[0].innerHTML } catch (error) { html = jqelem.innerHTML }
        }
    }
    var htmlChunk = marked.marked(html, { renderer: markdownParser });
    htmlChunk = removeEmTags(htmlChunk);
    try {
        elem_to_render_in.empty();
    } catch (error) {
        try {
            elem_to_render_in[0].innerHTML = ''
        } catch (error) { elem_to_render_in.innerHTML = '' }
    }
    try {
        elem_to_render_in[0].innerHTML = htmlChunk
    } catch (error) {
        try {
            elem_to_render_in.append(htmlChunk)
        } catch (error) {
            elem_to_render_in.innerHTML = htmlChunk
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
    Array.from(code_elems).forEach(function (code_elem) {
        // hljs.highlightBlock(code_elem);
    });
}

function loadDocumentsForMultiDoc(searchResultsAreaId, tagsAreaId, search_term = '', activeDocId = null) {
    var api;
    var search_mode;

    if (search_term.length > 0) {
        api = '/search_document?text=' + search_term;
        search_mode = true;
    } else {
        api = '/list_all';
        search_mode = false;
    }

    var request = apiCall(api, 'GET', {});
    request.done(function (data) {
        var searchResultsArea = $('#' + searchResultsAreaId);
        searchResultsArea.empty();

        var resultList = $('<ol></ol>'); // Create an ordered list
        var documentIds = [];
        $('.document-tag').each(function () {
            documentIds.push($(this).attr('data-doc-id'));
        });
        if (activeDocId) {
            data = data.filter(doc => doc.doc_id !== activeDocId);
        }
        data.filter(doc => !documentIds.includes(doc.doc_id)).forEach(function (doc, index) {
            var docItem = $(`
                <li class="my-2">
                    <a href="#" class="search-result-item d-block" data-doc-id="${doc.doc_id}">${doc.title}</a>
                </li>
            `);
            docItem.click(function (event) {
                event.preventDefault();
                addDocumentTags(tagsAreaId, [doc]);
            });
            resultList.append(docItem); // Append list items to the ordered list
        });
        searchResultsArea.append(resultList); // Append the ordered list to the search results area
    });

    return request;
}


function addDocumentTags(tagsAreaId, data) {

    data.forEach(function (doc) {
        var docTag = $(`
            <div class="document-tag bg-light border rounded mb-2 mr-2 p-2 d-inline-flex align-items-center" data-doc-id="${doc.doc_id}">
                <span class="me-2">${doc.title}</span>
                <button class="delete-tag-button btn btn-sm btn-danger">Delete</button>
            </div>`);
        var count = $('#' + tagsAreaId).children().length;
        var limit = 4
        if (count > limit - 1) {
            alert(`you cannot add more than ${limit} documents for Multiple Doc Search`);
        }
        else { $('#' + tagsAreaId).append(docTag); }
        // Handle click events for the delete button
        $('.delete-tag-button').click(function (event) {
            event.preventDefault();
            event.stopPropagation();
            $(this).parent().remove();
        });
    });
}

function copyToClipboard(textElem, textToCopy, mode = "text") {
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

    // if textToCopy is undefined, then we will copy the text from the textElem

    if (textToCopy === undefined) {
        var textToCopy = "";
        textElements.each(function () {
            var $this = $(this);
            if ($this.is("input, textarea")) {
                textToCopy += $this.val().replace(/\[show\]|\[hide\]/g, '') + "\n";
            } else {
                textToCopy += $this.text().replace(/\[show\]|\[hide\]/g, '') + "\n";
            }
        });
    }

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



function initSearchForMultipleDocuments(searchBoxId, searchResultsAreaId, tagsAreaId, activeDocId = null) {
    var lastTimeoutId = null;
    var previousSearchLength = 0;
    var searchBox = $('#' + searchBoxId);
    $('#' + tagsAreaId).empty();

    searchBox.on('input', function () {
        var currentSearchLength = searchBox.val().length;

        if (lastTimeoutId !== null) {
            clearTimeout(lastTimeoutId);
        }

        lastTimeoutId = setTimeout(function () {
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




function addOptions(parentElementId, type, activeDocId = null) {
    var checkBoxIds = [
        type === "assistant" ? `${parentElementId}-${type}-use-google-scholar` : `${parentElementId}-${type}-use-references-and-citations-checkbox`,
        `${parentElementId}-${type}-perform-web-search-checkbox`,
        `${parentElementId}-${type}-use-multiple-docs-checkbox`,
        `${parentElementId}-${type}-tell-me-more-checkbox`,
    ];
    slow_fast = `${parentElementId}-${type}-provide-detailed-answers-checkbox`
    var checkboxOneText = type === "assistant" ? "Scholar" : "References and Citations";
    var disabled = type === "assistant" ? "" : "disabled";



    $(`#${parentElementId}`).append(
        `<small><div class="row">` +
        `<div class="col-md-auto">` +
        `<div class="form-check form-check-inline" style="margin-right: 10px;"><input class="form-check-input" id="${checkBoxIds[0]}" type="checkbox" ${disabled}><label class="form-check-label" for="${checkBoxIds[0]}">${checkboxOneText}</label></div>` +

        `<div class="form-check form-check-inline" style="margin-right: 10px;"><input class="form-check-input" id="${checkBoxIds[1]}" type="checkbox"><label class="form-check-label" for="${checkBoxIds[1]}">Search</label></div>` +

        `<div class="form-check form-check-inline" style="margin-right: 10px;"><input class="form-check-input" id="${checkBoxIds[2]}" type="checkbox"><label class="form-check-label" for="${checkBoxIds[2]}">Docs</label></div>` +
        `<div class="form-check form-check-inline" style="margin-right: 10px;"><input class="form-check-input" id="${checkBoxIds[3]}" type="checkbox"><label class="form-check-label" for="${checkBoxIds[3]}">More</label></div>` +
        `</div>` +
        (type === "assistant" ? `
    <div class="col-md-auto">
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
        
        <div class="form-check form-check-inline" id="enablePreviousMessagesContainer" style="line-height: 0.9;">
            <div style="border: 1px solid #ccc; padding: 2px; border-radius: 12px; display: inline-flex; align-items: center;">
                <div style="margin-left: auto; margin-right: 5px;">History</div>
                <div style="display: flex; flex-direction: column; align-items: center; margin-right: 5px;">
                    <input type="radio" name="historyOptions" id="historyBan" value="-1" autocomplete="off">
                    <label for="historyBan"><small>∅</small></label>
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
                    <input type="radio" name="historyOptions" id="history3" value="3" autocomplete="off" checked>
                    <label for="history3"><small>3</small></label>
                </div>
                <div style="display: flex; flex-direction: column; align-items: center; margin-right: 5px;">
                    <input type="radio" name="historyOptions" id="historyInfinite" value="infinite" autocomplete="off">
                    <label for="historyInfinite"><small>∞</small></label>
                </div>
                
            </div>
        </div>
    

        <div class="form-check form-check-inline"><button id="deleteLastTurn" class="btn btn-danger rounded-pill mt-1">Del Last Turn</button></div>
    </div>
    <div class="col-md-auto mt-1">
        <div class="form-check form-check-inline mt-1" style="border: 1px solid #ccc; padding: 2px; border-radius: 12px; display: inline-flex; align-items: center;">
            <label for="preamble-selector" class="mr-1">Preambles</label>
            <select class="form-control selectpicker" id="preamble-selector" multiple>
                <option selected>md format</option>
                <option selected>better formatting</option>
                <option>Easy Copy</option>
                <option>Short reply</option>
                <option>Long reply</option>
                <option>CoT</option>
                <option selected>Short references</option>
                <option selected>Latex Eqn</option>
                <option>Explore</option>
                <option>Creative</option>
                <option>Argumentative</option>
                <option>Blackmail</option>
                <option selected>No Lazy</option>
                <option>Web Search</option>
            </select>
        </div>
        
        <div class="form-check form-check-inline mt-1" style="border: 1px solid #ccc; padding: 2px; border-radius: 12px; display: inline-flex; align-items: center;">
            <label for="main-model-selector" class="mr-1">Model</label>
            <select class="form-control" id="main-model-selector">
                <option selected>gpt-4-turbo</option>
                <option>gpt-4-32k</option>
                <option>cohere/command-r-plus</option>
                <option>Claude Opus</option>
                <option>Claude Sonnet</option>
                <option>Mistral Large</option>
                <option>Mistral Medium</option>
                <option>Gemini</option>
            </select>
        </div>
        
        <div class="form-check form-check-inline mt-1" style="border: 1px solid #ccc; padding: 2px; border-radius: 12px; display: inline-flex; align-items: center;">
            <label for="field-selector" class="mr-1">Field</label>
            <select class="form-control" id="field-selector">
                <option selected>None</option>
                <option>Science</option>
                <option>Arts</option>
                <option>Health</option>
                <option>Psychology</option>
                <option>Finance</option>
                <option>Mathematics</option>
                <option>QnA</option>
                <option>AI</option>
                <option>Software</option>
            </select>
        </div>
        <div class="form-check form-check-inline mt-1">
            <button class="btn btn-primary rounded-pill mt-1" id="memory-pad-text-open-button"><i class="bi bi-pen"></i>&nbsp;Memory</button>
        </div>

        <div class="form-check form-check-inline mt-1">
            <input class="form-check-input" id="use_memory_pad" type="checkbox">
            <label class="form-check-label" for="use_memory_pad">Use Pad</label>
        </div>
        
    </div>
    <div class="col-md-auto mt-1" style="width: 100%;">
        <div class="mt-1">
            <textarea id="permanentText" class="dynamic-textarea form-control" placeholder="Permanent Instruction."></textarea>
        </div>
    </div>
    `: '') +

        `</div></small>`
    );

    // $("#field-selector").on('change', function () {
    //     activeTab = $('#pdf-details-tab .nav-item .nav-link.active').attr('id');
    //     $(`#${activeTab}`).trigger('shown.bs.tab');
    //     if (currentDomain['domain'] !== 'search') {
    //         activateChatTab();
    //     }
    // });


    // Elements for Multiple Documents option
    var searchBox = $(`<input id="${parentElementId}-${type}-search-box" type="text" placeholder="Search for documents..." style="display: none;">`);
    var searchResultsArea = $(`<div id="${parentElementId}-${type}-search-results" style="display: none;"></div>`);
    var docTagsArea = $(`<div id="${parentElementId}-${type}-document-tags" style="display: none;"></div>`);

    // Add them to the parent element
    $(`#${parentElementId}`).append(searchBox, searchResultsArea, docTagsArea);

    // Add event handlers to make checkboxes mutually exclusive
    checkBoxIds.forEach(function (id, index) {
        $('#' + id).change(function () {
            if (this.checked) {
                checkBoxIds.forEach(function (otherId, otherIndex) {
                    if (index !== otherIndex) {
                        var otherCheckBox = $('#' + otherId);
                        if (otherCheckBox.is(':checked')) {
                            otherCheckBox.prop('checked', false).trigger('change');
                        }
                    }
                });
            }
        });
    });

    // Add an event handler on the Multiple Docs checkbox
    $('#' + checkBoxIds[2]).change(function () {
        if (this.checked) {
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
        $('#deleteLastTurn').click(function () {
            if (ConversationManager.activeConversationId) {
                ChatManager.deleteLastMessage(ConversationManager.activeConversationId);
            }
        });
    }
}



function getOptions(parentElementId, type) {
    checkBoxOptionOne = type === "assistant" ? "googleScholar" : "use_references_and_citations"
    optionOneChecked = $(type === "assistant" ? `#${parentElementId}-${type}-use-google-scholar` : `#${parentElementId}-${type}-use-references-and-citations-checkbox`).is(':checked');
    slow_fast = `${parentElementId}-${type}-provide-detailed-answers-checkbox`
    values = {
        perform_web_search: $(`#${parentElementId}-${type}-perform-web-search-checkbox`).is(':checked'),
        use_multiple_docs: $(`#${parentElementId}-${type}-use-multiple-docs-checkbox`).is(':checked'),
        tell_me_more: $(`#${parentElementId}-${type}-tell-me-more-checkbox`).is(':checked'),
        use_memory_pad: $('#use_memory_pad').is(':checked'),
    };
    let speedValue = $(`input[name='${slow_fast}Options']:checked`).val();
    values['provide_detailed_answers'] = speedValue;
    values[checkBoxOptionOne] = optionOneChecked;
    if (type === "assistant") {
        let historyValue = $("input[name='historyOptions']:checked").val();
        values['enable_previous_messages'] = historyValue;
    }
    var documentIds = [];
    $(`#${parentElementId}`).find('.document-tag').each(function () {
        documentIds.push($(this).attr('data-doc-id'));
    });
    values['additional_docs_to_read'] = documentIds;
    if (type === "assistant") {
        values['preamble_options'] = $('#preamble-selector').val();
        values['main_model'] = $('#main-model-selector').val();
        values['field'] = $('#field-selector').val();
        values["permanentText"] = $("#permanentText").val();
    }
    return values
}

function resetOptions(parentElementId, type) {
    $(type === "assistant" ? `${parentElementId}-${type}-use-google-scholar` : `${parentElementId}-${type}-use-references-and-citations-checkbox`).prop('checked', false);
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
    $(type === "assistant" ? `#${parentElementId}-${type}-use-google-scholar` : `#${parentElementId}-${type}-use-references-and-citations-checkbox`).parent().remove();
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

function isAbsoluteUrl(url) {
    // A simple way to check if the URL is absolute is by looking for the presence of '://'
    return url.indexOf('://') > 0;
};


function apiCall(url, method, data, useFetch = false) {
    //     url = appendKeyStore(url);

    if (useFetch) {
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
            return $.post({ url: url, data: JSON.stringify(data), contentType: 'application/json' });
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

function showPDF(pdfUrl, subtree, url=null) {
    var parent_of_view = document.getElementById(`${subtree}`);
    var xhr = new XMLHttpRequest();
    var progressBar = parent_of_view.querySelector('#progressbar');
    var progressStatus = parent_of_view.querySelector('#progress-status');
    var viewer = parent_of_view.querySelector("#pdfjs-viewer");
    progressBar.style.width = '0%';
    progressStatus.textContent = '';
    viewer.style.display = 'none';  // Hide the viewer while loading
    document.getElementById('progress').style.display = 'block';  // Show the progress bar

    if (url) {
        xhr.open('GET', `${url}?file=` + encodeURIComponent(pdfUrl), true);
    } else {
        xhr.open('GET', '/proxy?file=' + encodeURIComponent(pdfUrl), true);
    }
    
    xhr.responseType = 'blob';

    // Track progress
    xhr.onprogress = function (e) {
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


    xhr.onload = function (e) {


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
                var height = ($("#pdf-questions").is(':hidden') || $("#pdf-questions").length === 0) ? $(window).height() : $(window).height() * 0.8;
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
