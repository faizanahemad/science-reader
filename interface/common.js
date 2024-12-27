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
    }, 480000);  // 8 minute timeout

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

function getMimeType(file) {
    var extension = file.name.split('.').pop().toLowerCase();
    var mimeTypeMap = {
        'pdf': 'application/pdf',
        'doc': 'application/msword',
        'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'txt': 'text/plain',
        'jpeg': 'image/jpeg',
        'jpg': 'image/jpeg',
        'png': 'image/png',
        'svg': 'image/svg+xml',
        'bmp': 'image/bmp',
        'rtf': 'application/rtf',
        'xls': 'application/vnd.ms-excel',
        'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'csv': 'text/csv',
        'tsv': 'text/tab-separated-values',
        'parquet': 'application/parquet',
        'json': 'application/json',
        'jsonl': 'application/x-jsonlines',
        'ndjson': 'application/x-ndjson'
    };
    return mimeTypeMap[extension] || 'application/octet-stream'; // Default MIME type  
}  

function getFileType(file, callback) {
    var filetypedict = {};
    var reader = new FileReader();
    reader.onload = function (e) {
        var mimeType = e.target.result.match(/data:([^;]*);/)[1];
        filetypedict["mimeType"] = mimeType;
        callback(mimeType); // Pass the MIME type to the callback function  
    };
    reader.onerror = function (e) {
        console.error("Error reading file:", e);
        callback(null); // Pass null to the callback in case of an error  
    };
    reader.readAsDataURL(file);
    return filetypedict;
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
    let copyBtn = $('<button>').addClass('vote-btn').addClass('copy-btn').text('📋');
    let editBtn = $('<button>').addClass('vote-btn').addClass('edit-btn').text('✏️');
    copyBtn.click(function () {
        // Here we get the card text and copy it to the clipboard
        // let cardText = cardElem.text().replace(/\[show\]|\[hide\]/g, '');
        copyToClipboard(cardElem, text.replace('<answer>', '').replace('</answer>', ''));
    });
    editBtn.off();
    editBtn.click(function () {
        $('#message-edit-text').val(text);
        $('#message-edit-modal').modal('show');
        $('#message-edit-text-save-button').off();
        messageId = cardElem.find('.card-header').last().attr('message-id');
        messageIndex = cardElem.find('.card-header').last().attr('message-index');

        $('#message-edit-text-save-button').click(function () {
            
            var newtext = $('#message-edit-text').val();
            ConversationManager.saveMessageEditText(newtext, messageId, messageIndex, cardElem);
            $('#message-edit-modal').modal('hide');
        });
    });

    let voteBox = $('<div>').addClass('vote-box').css({
        'position': 'absolute',
        'top': '5px',
        'right': '30px'
    });
    
    voteBox.append(editBtn);
    voteBox.append(copyBtn);
    // delete any previous votebox and add the new one
    cardElem.find('.vote-box').remove();
    cardElem.append(voteBox);
    return
}
const markdownParser = new marked.Renderer();
marked.setOptions({
    renderer: markdownParser,
    highlight: function (code, language) {
        const validLanguage = hljs.getLanguage(language) ? language : 'plaintext';
        if (validLanguage === 'plaintext') {
            return hljs.highlightAuto(code).value;
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
    const validLanguage = hljs.getLanguage(language) ? language : 'plaintext';
    if (validLanguage === 'plaintext') {
        var highlighted = hljs.highlightAuto(code).value;
    } else {
        var highlighted = hljs.highlight(validLanguage, code).value;
    }
    
    // var highlighted = validLang ? hljs.highlight(code, { language }).value : code;

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

function hasUnclosedMermaidTag(htmlString) {
    // Regular expression to identify all relevant mermaid tags
    const tagRegex = /<pre class='mermaid'>|<\/pre>|```mermaid|```(?!\w)/g;
    let stack = [];
    let match;

    while ((match = tagRegex.exec(htmlString)) !== null) {
        switch (match[0]) {
            case "<pre class='mermaid'>":
                // Push the expected closing tag for <pre class='mermaid'>
                stack.push("</pre>");
                break;
            case "```mermaid":
                // Push the expected closing tag for ```mermaid
                stack.push("```");
                break;
            case "</pre>":
            case "```":
                // Check if the closing tag matches the expected one from the stack
                if (stack.length === 0 || stack.pop() !== match[0]) {
                    return true; // Mismatch found or stack is empty (unmatched closing tag)
                }
                break;
        }
    }

    return stack.length > 0; // If the stack is not empty, there is at least one unclosed tag
}
 


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
    // remove <answer> and </answer> tags
    // check html has </answer> tag
    has_end_answer_tag = html.includes('</answer>')
    html = html.replace(/<answer>/g, '').replace(/<\/answer>/g, '');
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
    MathJax.Hub.Queue(function() {
        // determine if html above has an open <pre class='mermaid'> tag that isn't closed.
        if (!hasUnclosedMermaidTag(html) && has_end_answer_tag) {
            possible_mermaid_elem = elem_to_render_in.find(".hljs.mermaid")
            // if the next element after the possible_mermaid_elem is not a pre element with class mermaid then only render
            if (possible_mermaid_elem.length & !possible_mermaid_elem.next().hasClass('mermaid') & !possible_mermaid_elem.closest('.code-block').next().hasClass('mermaid')) {
                mermaid_text = possible_mermaid_elem[0].textContent
                mermaid_elem = $("<pre class='mermaid'></div>")
                mermaid_elem.text(mermaid_text)
                // append as sibling to the possible_mermaid_elem
                possible_mermaid_elem.after(mermaid_elem)
            }
            mermaid.run({
                querySelector: 'pre.mermaid',
                useMaxWidth: false,
                suppressErrors: true,

            }).then(() => {
                // find all svg inside .mermaid class pre elements.
                var svgs = $(document).find('pre.mermaid svg');
                // iterate over each svg element and unset its height attribute
                svgs.each(function (index, svg) {
                    $(svg).attr('height', null);
                });
            });
        }
        
        code_elems = $(elem_to_render_in).find('code')
        Array.from(code_elems).forEach(function (code_elem) {
            hljs.highlightBlock(code_elem);
        });
        let permittedTagNames = ["DIV", "SPAN", "SECTION", "BODY"];
        waitForDrawIo(function (timeout) {
            let diagrams = document.querySelectorAll(".drawio-diagram");

            diagrams.forEach(function (diagram) {
                if (permittedTagNames.indexOf(diagram.tagName) === -1) {
                    return; //not included in a permitted tag
                }

                if (timeout) {
                    showError(diagram, "Unable to load draw.io renderer");
                    return;
                }

                processDiagram(diagram);
            });
        })
    })
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





function addOptions(parentElementId, type, activeDocId = null) {
    var checkBoxIds = [
        `${parentElementId}-${type}-use-google-scholar`,
        `${parentElementId}-${type}-perform-web-search-checkbox`,
        `${parentElementId}-${type}-use-multiple-docs-checkbox`,
        `${parentElementId}-${type}-tell-me-more-checkbox`,
        `${parentElementId}-${type}-search-exact`,
        `${parentElementId}-${type}-ensemble`,
    ];
    slow_fast = `${parentElementId}-${type}-provide-detailed-answers-checkbox`
    var checkboxOneText = type === "assistant" ? "Scholar" : "References and Citations";
    var disabled = type === "assistant" ? "" : "disabled";



    $(`#${parentElementId}`).append(
        `<small><div class="row">` +
        `<div class="col-md-auto">` +
        `<div class="form-check form-check-inline" style="margin-right: 10px;"><input class="form-check-input" id="${checkBoxIds[0]}" type="checkbox" ${disabled}><label class="form-check-label" for="${checkBoxIds[0]}">${checkboxOneText}</label></div>` +

        `<div class="form-check form-check-inline" style="margin-right: 10px;"><input class="form-check-input" id="${checkBoxIds[1]}" type="checkbox"><label class="form-check-label" for="${checkBoxIds[1]}">Search</label></div>` +
        `<div class="form-check form-check-inline" style="margin-right: 10px; display:none;"><input class="form-check-input" id="${checkBoxIds[3]}" type="checkbox"><label class="form-check-label" for="${checkBoxIds[3]}">More</label></div>` +
        `<div class="form-check form-check-inline" style="margin-right: 10px;"><input class="form-check-input" id="${checkBoxIds[4]}" type="checkbox"><label class="form-check-label" for="${checkBoxIds[4]}">Search Exact</label></div>` +
        `<div class="form-check form-check-inline" style="margin-right: 10px;"><input class="form-check-input" id="${checkBoxIds[5]}" type="checkbox"><label class="form-check-label" for="${checkBoxIds[4]}">Ensemble</label></div>` +
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
                <option>Is Coding Request</option>
                <option>Paper Summary</option>
                <option selected>Long</option>
                <option selected>Explain Maths</option>
                <option>No Lazy</option>
                <option>Argumentative</option>
                <option>Blackmail</option>
                <option>ML System Design Roleplay</option>
                <option>No Links</option>
                
                <option>ML System Design Answer</option>
                <option>ML System Design Answer Short</option>
                <option>Easy Copy</option>
                
                <option>CoT</option>
                <option>Short</option>
                
                
                <option>no ai</option>
                
                <option>md format</option>
                <option>TTS</option>
                <option>better formatting</option>
                <option>no format</option>
                
                <option>No Code Exec</option>
                <option>Code Exec</option>
                
                <option>Short references</option>
                <option>Latex Eqn</option>
                <option>Comparison</option>
                <option>Explore</option>
                <option>Creative</option>
                
                
                <option>Web Search</option>
            </select>
        </div>
        
        <div class="form-check form-check-inline mt-1" style="border: 1px solid #ccc; padding: 2px; border-radius: 12px; display: inline-flex; align-items: center;">
            <label for="main-model-selector" class="mr-1">Model</label>
            <select class="form-control" id="main-model-selector" multiple>
                <option selected>Claude Sonnet 3.5</option>   
                
                <option>openai/o1-preview</option>
                
                
                <option>gpt-4o</option>
                <option>Gemini 1.5</option>

                <option>Filler</option>
                <option>Claude Opus</option>
                <option>Pixtral Large</option>
                <option>o1-preview</option>

                
                <option>o1</option>
                
                
                
                
                <option>openai/o1</option>
                
                
                

                <!-- option>Mistral Large</option -->
                <option>gpt-4-turbo</option>
                <!-- option>o1-mini</option -->
                <!-- option>openai/o1-mini</option -->
                <!-- option>Command-r+</option -->
                <option>DeepSeek-V2.5 Chat</option>
                <!-- option>Jamba</option -->
                <option>llama-3.1-405b</option>
                <!-- option>Qwen 2</option -->
                
                
                <option>Hermes llama-3.1-405b</option>
                <!-- option>gpt-4-32k</option -->
                 
                
                
                
                
                 
                
                <!-- option>gpt-4-0314</option -->
                <!-- option>gpt-4-32k-0314</option -->
                
                
                <!-- option>deepseek/deepseek-coder</option -->
                <!-- option>PPX 405B Online</option -->
                <!-- option>Yi Large</option -->
                
                <!-- option>llama-3.1-70b</option -->
                
                
                
                
                
                
                
                
            </select>
        </div>
        
        <div class="form-check form-check-inline mt-1" style="border: 1px solid #ccc; padding: 2px; border-radius: 12px; display: inline-flex; align-items: center;">
            <label for="field-selector" class="mr-1">Agents</label>
            <select class="form-control" id="field-selector">
                <option selected>None</option>
                <option>Agent_PerplexitySearch</option>
                <option>Agent_WebSearch</option>
                <option>Agent_BroadSearch</option>
                <option>Agent_BestOfN</option>
                <option>Agent_NResponseAgent</option>
                <option>Agent_LiteratureReview</option>
                
                <option>Prompt_IdeaNovelty</option>
                <option>Prompt_IdeaComparison</option>
                <option>Prompt_IdeaFleshOut</option>
                <option>Prompt_IdeaDatasetsAndExperiments</option>
                <option>Prompt_IdeaAblationsAndResearchQuestions</option>
                <option>Prompt_ResearchPreventRejections</option>
                
                <option>Agent_IdeaNovelty</option>
                
                <option>Agent_CodeExecution</option>
                <option>Agent_VerifyAndImprove</option>
                <option>Agent_ElaborateDiveDeepExpand</option>
                <option>Agent_Finance</option>
                <option>Agent_DocQnA</option>
            </select>
        </div>
        <div class="form-check form-check-inline mt-1">
            <button class="btn btn-primary rounded-pill mt-1" id="memory-pad-text-open-button"><i class="bi bi-pen"></i>&nbsp;Memory</button>
        </div>

        <div class="form-check form-check-inline mt-1">
            <input class="form-check-input" id="use_memory_pad" type="checkbox">
            <label class="form-check-label" for="use_memory_pad">Use Pad</label>
        </div>

        <div class="form-check form-check-inline mt-1">
            <input class="form-check-input" id="enable_planner" type="checkbox">
            <label class="form-check-label" for="enable_planner">Planner</label>
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
    
    if (type === 'assistant') {
        $('#deleteLastTurn').click(function () {
            if (ConversationManager.activeConversationId) {
                ChatManager.deleteLastMessage(ConversationManager.activeConversationId);
            }
        });
    }
}



function getOptions(parentElementId, type) {
    checkBoxOptionOne = "googleScholar"
    optionOneChecked = $(type === "assistant" ? `#${parentElementId}-${type}-use-google-scholar` : `#${parentElementId}-${type}-use-references-and-citations-checkbox`).is(':checked');
    slow_fast = `${parentElementId}-${type}-provide-detailed-answers-checkbox`
    values = {
        perform_web_search: $(`#${parentElementId}-${type}-perform-web-search-checkbox`).is(':checked'),
        use_multiple_docs: $(`#${parentElementId}-${type}-use-multiple-docs-checkbox`).is(':checked'),
        tell_me_more: $(`#${parentElementId}-${type}-tell-me-more-checkbox`).is(':checked'),
        use_memory_pad: $('#use_memory_pad').is(':checked'),
        enable_planner: $('#enable_planner').is(':checked'),
        search_exact: $(`#${parentElementId}-${type}-search-exact`).is(':checked'),
        ensemble: $(`#${parentElementId}-${type}-ensemble`).is(':checked'),
    };
    let speedValue = $(`input[name='${slow_fast}Options']:checked`).val();
    values['provide_detailed_answers'] = speedValue;
    values[checkBoxOptionOne] = optionOneChecked;
    if (type === "assistant") {
        let historyValue = $("input[name='historyOptions']:checked").val();
        values['enable_previous_messages'] = historyValue;
    }
    
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
    $(`#${parentElementId}-${type}-search-exact`).prop('checked', false);
    $(`#${parentElementId}-${type}-ensemble`).prop('checked', false);
    // $(`#${parentElementId}-${type}-search-exact`).prop('checked', false);


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
    $(`#${parentElementId}-${type}-search-exact`).parent().remove();
    $(`#${parentElementId}-${type}-ensemble`).parent().remove();

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
