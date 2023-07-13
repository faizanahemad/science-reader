function showMore(parentElem, text=null, textElem=null, as_html=false, show_at_start=false){
    
    if (textElem) {
        
        if (as_html){
            var text = textElem.html()
        }
        else {
            var text = textElem.text()
        }
        
    }
    else if (text) {
        var textElem = $('<small class="summary-text"></small>');
    } else {
        throw "Either text or textElem must be provided to `showMore`"
    }
    
    if (as_html) {
        
        var moreText = $('<span class="more-text" style="display:none;"></span>')
        moreText.html(text)
        moreText.find('.show-more').each(function(){$(this).remove();})
        shortText = moreText.text().slice(0, 100);
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
        var moreText = text.slice(200);
        if(moreText) {
            var lessText = text.slice(0, 200);
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
            disableMainFunctionality();
        }
    });
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
        pseudoUserId = crypto.randomUUID();
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
            alert(`An error occurred: ${textStatus}, ${errorThrown}`);
        })
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

                // if OpenAI key is provided, verify it and fetch the list of models
                if (key === 'openAIKey' && keyString) {
                    disableMainFunctionality();
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
};



function isAbsoluteUrl(url) {
  // A simple way to check if the URL is absolute is by looking for the presence of '://'
  return url.indexOf('://') > 0;
};

function appendDictToUrl(dict, url) {
    if (isAbsoluteUrl(url)) {
        urlObj = new URL(url);
    } else {
        // If the URL is relative, provide the base URL (origin of the current page)
        urlObj = new URL(url, window.location.origin);
    }
    const params = new URLSearchParams(urlObj.search);
    for (const key in dict) {
        params.append(key, dict[key]);
    }
    urlObj.search = params.toString();
    return urlObj.toString();
}

function appendKeyStore(url) {
    return appendDictToUrl(keyStore, url)
}

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

        return fetch(url, options);
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
    
    var activeDocId = null;
    var pdfUrl = null;
    const markdownParser = new marked.Renderer();
    function renderInnerContentAsMarkdown(jqelem, callback=null, continuous=false){
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
        
        try {
            html = jqelem.html()
        } catch(error) {
            try{html = jqelem[0].innerHTML} catch (error) {html = jqelem.innerHTML}
        }
        var htmlChunk = marked.marked(html, { renderer: markdownParser });
        htmlChunk = removeEmTags(htmlChunk);
        try{elem_to_render_in.empty();} catch(error){
            try{elem_to_render_in[0].innerHTML=''} catch (error) {elem_to_render_in.innerHTML=''}
        }
        try{elem_to_render_in.append(htmlChunk)} catch(error){
            try{elem_to_render_in[0].innerHTML=htmlChunk} catch (error) {elem_to_render_in.innerHTML=htmlChunk}
        }
        mathjax_elem = elem_to_render_in[0]
        if (mathjax_elem === undefined) {
            mathjax_elem = jqelem
        }
        MathJax.Hub.Queue(["Typeset", MathJax.Hub, mathjax_elem]);
        if (callback) {
            MathJax.Hub.Queue(callback)
        }
    }
    
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
                    var height = $(window).height() * 0.8;
                    $('#pdf-content').css({
                        'width': width,
                        'height': height,
                    });
                    $(viewer).css({
                        'width': '100%',
                        'height': '100%',
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
    
    function initialiseVoteBank(cardElem, text, contentId=null) {
        let voteCountElem = $('<p>').addClass('vote-count');
        let upvoteBtn = $('<button>').addClass('vote-btn').addClass('upvote-btn').text('👍');
        let downvoteBtn = $('<button>').addClass('vote-btn').addClass('downvote-btn').text('👎');

        let voteBox = $('<div>').addClass('vote-box').css({
            'position': 'absolute',
            'top': '10px',
            'right': '20px'
        });
        voteBox.append(upvoteBtn, voteCountElem, downvoteBtn);
        cardElem.append(voteBox);

        function updateVoteCount() {
            if (contentId) {
                var request = $.getJSON('/getUpvotesDownvotesByQuestionId/' + contentId);
                
            } else {
                var request = $.ajax({
                    url: '/getUpvotesDownvotesByQuestionId/' + contentId,
                    type: 'GET',
                    data: JSON.stringify({doc_id: activeDocId, question_text: text}),
                    dataType: 'json',
                    contentType: 'application/json',
                });
            }
            
            
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
            if (contentId) {
                
                var request = $.getJSON('/getUpvotesDownvotesByQuestionIdAndUser', {question_id: contentId});
            } else {
                var request = $.ajax({
                    url: '/getUpvotesDownvotesByQuestionIdAndUser',
                    type: 'GET',
                    data: JSON.stringify({doc_id: activeDocId, question_text: text}),
                    dataType: 'json',
                    contentType: 'application/json',
                });
            }
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

                var summaryColClass = qnaExists && deepDetailsExists ? "col-4" : "col-6";

                row.append('<div id="summary-column" class="' + summaryColClass + '"></div>');

                if (qnaExists) {
                    row.append('<div id="qna-column" class="col-4"></div>');
                }

                if (deepDetailsExists) {
                    row.append('<div id="deep-details-column" class="col-4"></div>');
                }

                // Populate the summary column
                $('#summary-column').append('<h4>Short Summary</h4>');
                if (data.summary === '') {
                    
                    $('#summary-column').append('<p id="summary-text">Details not loaded yet</p>');
                    $('#summary-column').append('<button id="get-summary-details-button" type="button" class="btn btn-primary">Get Details</button>');
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
                                accumulator = ''
                                if (paragraph.html().length > content_length + 100){
                                    renderInnerContentAsMarkdown(paragraph, 
                                                                 callback=null, continuous=true)
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
                        });
                    });

                } else {
                    $('#summary-column').append('<p id="summary-text">' + data.summary + '</p>');
                    renderInnerContentAsMarkdown($('#summary-text'), function(){
                        showMore(null, text=null, textElem=$('#summary-text'), as_html=true);
                    });
                    
                }

                $('#summary-column').append('<h4>Elaborate Summary</h4>');
                var chunkContainer = $('<div class="summary-text"></div>')
                chunked_summary = data.details.chunked_summary;

                for (var i = 0; i < chunked_summary.length; i++) {
                    // $('#summary-column').append('<h5>' + titles[i] + '</h5>');
                    chunkContainer.append('<p>' + data.details.chunked_summary[i] + '</p></br>');
                }
                if (chunked_summary.length > 0 && chunked_summary[0].length > 0) {
                    $('#summary-column').append(chunkContainer)
                    renderInnerContentAsMarkdown(chunkContainer, function(){
                        showMore(null, text=null, textElem=chunkContainer, as_html=true);
                    });
                }
                
                // Populate the QnA column if exists
                if (qnaExists) {
                    $('#qna-column').append('<h4>Questions and Answers</h4>');
                   
                    data.details.detailed_qna.forEach(function(one_qa) {
                        let card = $('<div>').addClass('card').attr("content-id", one_qa[0]);
                        let cardBody = $('<div>').addClass('card-body');
                        card.append(cardBody);
                        cardBody.append('<p><strong>Q:</strong> ' + one_qa[1] + '</p>');
                        var ansArea = $('<p><strong>A:</strong></p>')
                        var ansContainer = $('<span class = "summary-text">' + one_qa[2] +'</span>')
                        ansArea.append(ansContainer)
                        cardBody.append(ansArea);
                        $('#qna-column').append(card);
                        initialiseVoteBank(card, one_qa[1], one_qa[0]);
                        renderInnerContentAsMarkdown(ansContainer, function(){
                            showMore(null, text=null, textElem=ansContainer, as_html=true);
                        });
                        
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
                            initialiseVoteBank(card, key, data.details.deep_reader_details[key]["id"]);
                            renderInnerContentAsMarkdown($(`#${key}-text`), function(){
                                if (data.details.deep_reader_details[key]["text"].trim().length > 0){
                                    showMore(null, text=null, textElem=$(`#${key}-text`), as_html=true);
                                }
                            });
                            
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
                                    while (true) {
                                        let { value, done } = await reader.read();
                                        if (done) {
                                            break;
                                        }
                                        let part = decoder.decode(value);
                                        $('#' + key + '-text').append(part);
                                        if ($('#' + key + '-text').html().length > content_length + 100){
                                            renderInnerContentAsMarkdown($('#' + key + '-text'), 
                                                                         callback=null, continuous=true)
                                            content_length = $('#' + key + '-text').html().length
                                        }
                                    }
                                    renderInnerContentAsMarkdown($('#' + key + '-text'), function(){
                                        showMore(null, text=null, textElem=$('#' + key + '-text'), 
                                                 as_html=true, show_at_start=true);
                                    });
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
                var deleteButton = $('<button class="btn p-0 ms-2 delete-button"><i class="bi bi-trash-fill"></i></button>');
                docItem.append('<strong>' + doc.title.slice(0, 100) + '</strong></br>');
                docItem.append(deleteButton);
                docItem.append('&nbsp;<span>' + '<a class="sidebar-source-link" href="' + doc.source +'">' + "PDF Link" + '</a>' + '</span></br>');
                // Append delete button to docItem
                
                showMore(docItem, doc.short_summary)
                $('#documents').append(docItem);
                
                if (autoselect){
                    if (firstDoc) {
                        setActiveDoc(doc.doc_id);
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
                var docId = $(this).parent().attr('data-doc-id');
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
    
    function loadDocumentsForMultiDoc(searchResultsAreaId, tagsAreaId, search_term='') {
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

            data.filter(doc=>doc.doc_id !== activeDocId).filter(doc=>!documentIds.includes(doc.doc_id)).forEach(function(doc, index) {
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



    
    function initSearchForMultipleDocuments(searchBoxId, searchResultsAreaId, tagsAreaId){
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
                    loadDocumentsForMultiDoc(searchResultsAreaId, tagsAreaId, searchBox.val());
                } else if (currentSearchLength === 0 && previousSearchLength >= 1) {
                    loadDocumentsForMultiDoc(searchResultsAreaId, tagsAreaId, '');
                }
                previousSearchLength = currentSearchLength;

                lastTimeoutId = null; 
            }, 400);
        });
    }

    
    function highLightActiveDoc(){
        $('#documents .list-group-item').removeClass('active');
        $('#documents .list-group-item[data-doc-id="' + activeDocId + '"]').addClass('active');
    }

    function setActiveDoc(docId) {
        activeDocId = docId;
        loadCitationsAndReferences();
        highLightActiveDoc();
        setupAskQuestionsView();
        setupViewDetailsView();
    }
    
    function addOptions(parentElementId, type) {
        var checkBoxIds = [
            `${parentElementId}-${type}-use-references-and-citations-checkbox`,
            `${parentElementId}-${type}-perform-web-search-checkbox`,
            `${parentElementId}-${type}-use-multiple-docs-checkbox`,
            `${parentElementId}-${type}-provide-detailed-answers-checkbox`
        ];

        $(`#${parentElementId}`).append(
            `<div style="display: flex; margin-bottom: 10px;">` +

            `<div class="form-check form-check-inline" style="margin-right: 20px;"><input class="form-check-input" id="${checkBoxIds[0]}" type="checkbox"><label class="form-check-label" for="${checkBoxIds[0]}">References & Citations</label></div>` +

            `<div class="form-check form-check-inline" style="margin-right: 20px;"><input class="form-check-input" id="${checkBoxIds[1]}" type="checkbox"><label class="form-check-label" for="${checkBoxIds[1]}">Web Search</label></div>` +

            `<div class="form-check form-check-inline" style="margin-right: 20px;"><input class="form-check-input" id="${checkBoxIds[2]}" type="checkbox"><label class="form-check-label" for="${checkBoxIds[2]}">Multiple Docs</label></div>` +

            `<div class="form-check form-check-inline"><input class="form-check-input" id="${checkBoxIds[3]}" type="checkbox"><label class="form-check-label" for="${checkBoxIds[3]}">Detailed Answers</label></div>` +
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
                initSearchForMultipleDocuments(`${parentElementId}-${type}-search-box`, `${parentElementId}-${type}-search-results`, `${parentElementId}-${type}-document-tags`);
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
    }



    function getOptions(parentElementId, type) {
        return {
            use_references_and_citations: $(`#${parentElementId}-${type}-use-references-and-citations-checkbox`).is(':checked'),
            perform_web_search: $(`#${parentElementId}-${type}-perform-web-search-checkbox`).is(':checked'),
            use_multiple_docs: $(`#${parentElementId}-${type}-use-multiple-docs-checkbox`).is(':checked'),
            provide_detailed_answers: $(`#${parentElementId}-${type}-provide-detailed-answers-checkbox`).is(':checked')
        };
    }

    function resetOptions(parentElementId, type) {
        $(`#${parentElementId}-${type}-use-references-and-citations-checkbox`).prop('checked', false);
        $(`#${parentElementId}-${type}-perform-web-search-checkbox`).prop('checked', false);
        $(`#${parentElementId}-${type}-use-multiple-docs-checkbox`).prop('checked', false);
        $(`#${parentElementId}-${type}-provide-detailed-answers-checkbox`).prop('checked', false);
        
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
        $(`#${parentElementId}-${type}-use-references-and-citations-checkbox`).parent().remove();
        $(`#${parentElementId}-${type}-perform-web-search-checkbox`).parent().remove();
        $(`#${parentElementId}-${type}-use-multiple-docs-checkbox`).parent().remove();
        $(`#${parentElementId}-${type}-provide-detailed-answers-checkbox`).parent().remove();
        
        $(`[id$="${type}-search-box"]`).remove();
        $(`[id$="${type}-document-tags"]`).remove();
        $(`[id$="${type}-search-results"]`).remove();

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
        addOptions('questions-view', 'query');

        async function askQuestion() {
            $("#answers").removeAttr('style')
            var query = $('#question-input').val();
            if (query && query.trim() !== '') {
                removeFollowUpView();

                $('#question-input').prop('disabled', true);
                $('#submit-question-button').prop('disabled', true);
                $('#loading').show();
                let options = getOptions('questions-view', 'query');
                var documentIds = [];
                $('.document-tag').each(function() {
                    documentIds.push($(this).attr('data-doc-id'));
                });
                let response = await apiCall('/streaming_get_answer', 'POST', { doc_id: activeDocId, query: query,"additional_docs_to_read": documentIds, ...options}, useFetch = true);

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
                    if (answerParagraph.html().length > content_length + 100){
                        renderInnerContentAsMarkdown(answerParagraph, 
                                                     callback=null, continuous=true)
                        content_length = answerParagraph.html().length
                    }
                }
                renderInnerContentAsMarkdown(answerParagraph, function(){
                    showMore(null, text=null, textElem=answerParagraph, as_html=true, show_at_start=true);
                });
                initialiseVoteBank(card, query,);
                // Append a 'More Details' button to the card that streams more details
                let moreDetailsButton = $('<button>').addClass('btn btn-primary').text('More Details');
                let moreDetailsCount = 0;
                moreDetailsButton.click(async function () {
                    $('#loading').show();
                    moreDetailsCount++;
                    moreDetailsButton.prop('disabled', true); // Disable the button
                    let moreDetailsResponse = await apiCall('/streaming_get_more_details', 'POST', { doc_id: activeDocId, query:query, previous_answer: answer, more_details_count: moreDetailsCount}, useFetch = true);

                    if (!moreDetailsResponse.ok) {
                        alert('An error occurred: ' + moreDetailsResponse.status);
                        return;
                    }
                    var content_length = 0
                    let moreDetailsReader = moreDetailsResponse.body.getReader();
                    while (true) {
                        let { value, done } = await moreDetailsReader.read();
                        if (done) {
                            break;
                        }
                        let part = decoder.decode(value);
                        answerParagraph.append(part);
                        answer = answer + part;
                        if (answerParagraph.html().length > content_length + 100){
                            renderInnerContentAsMarkdown(answerParagraph, 
                                                         callback=null, continuous=true)
                            content_length = answerParagraph.html().length
                        }
                    }
                    renderInnerContentAsMarkdown(answerParagraph, function(){
                        showMore(null, text=null, textElem=answerParagraph, as_html=true, show_at_start=true);
                    });
                    moreDetailsButton.prop('disabled', false); // Enable the button again
                    moreDetailsButton.remove();
                    $('#loading').hide();
                });
                cardBody.append(moreDetailsButton);

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
            if (e.which == 13) {
                askQuestion();
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
        addOptions('followup-view', 'followup');
        view.append('<div id="loading-follow-up" style="display:none;"><div class="spinner-border text-primary" role="status"><span class="sr-only">Loading...</span></div></div>');

        async function askFollowUpQuestion() {
            var query = $('#follow-up-question-input').val();
            if (query && query.trim() !== '') {
                $('#follow-up-question-input').prop('disabled', true); // Disable the input box
                $('#submit-follow-up-question-button').prop('disabled', true); // Disable the submit button
                $('#loading-follow-up').show(); // Show the loading spinner
                let options = getOptions('followup-view', 'followup');
                var documentIds = [];
                $('.document-tag').each(function() {
                    documentIds.push($(this).attr('data-doc-id'));
                });
                let response = await apiCall('/streaming_get_followup_answer', 'POST', { doc_id: activeDocId, query: query, previous_answer: previousAnswer, "additional_docs_to_read": documentIds, ...options }, useFetch = true);
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
                    let part = decoder.decode(value);
                    answerParagraph.append(part);
                    answer = answer + part
                    if (answerParagraph.html().length > content_length + 100){
                        renderInnerContentAsMarkdown(answerParagraph, 
                                                     callback=null, continuous=true)
                        content_length = answerParagraph.html().length
                    }
                }
                renderInnerContentAsMarkdown(answerParagraph, function(){
                    showMore(null, text=null, textElem=answerParagraph, as_html=true, show_at_start=true);
                });
                initialiseVoteBank(card, previousAnswer["query"]+ ". followup:" +query,);
                
                // Append a 'More Details' button to the card that streams more details
                let moreDetailsButton = $('<button>').addClass('btn btn-primary').text('More Details');
                let moreDetailsCount = 0;
                moreDetailsButton.click(async function () {
                    $('#loading-follow-up').show();
                    moreDetailsCount++;
                    moreDetailsButton.prop('disabled', true); // Disable the button
                    let moreDetailsResponse = await apiCall('/streaming_get_more_details', 'POST',{ doc_id: activeDocId, query:query, previous_answer: answer, more_details_count: moreDetailsCount}, useFetch = true);

                    if (!moreDetailsResponse.ok) {
                        alert('An error occurred: ' + moreDetailsResponse.status);
                        return;
                    }
                    
                    var content_length = 0
                    let moreDetailsReader = moreDetailsResponse.body.getReader();
                    while (true) {
                        let { value, done } = await moreDetailsReader.read();
                        if (done) {
                            break;
                        }
                        let part = decoder.decode(value);
                        answerParagraph.append(part);
                        answer = answer + part;
                        if (answerParagraph.html().length > content_length + 100){
                            renderInnerContentAsMarkdown(answerParagraph, 
                                                         callback=null, continuous=true)
                            content_length = answerParagraph.html().length
                        }
                    }
                    renderInnerContentAsMarkdown(answerParagraph, function(){
                        showMore(null, text=null, textElem=answerParagraph, as_html=true, show_at_start=true);
                    });
                    moreDetailsButton.prop('disabled', false); // Enable the button again
                    moreDetailsButton.remove();
                    $('#loading-follow-up').hide();
                });
                cardBody.append(moreDetailsButton);

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
            if (e.which == 13) {
                askFollowUpQuestion();
                return false; // Prevents the default action
            }
        });
    }


    
    function setupPDFModalSubmit() {
        $('#add-document-button').click(function() {
            $('#add-document-modal').modal('show');
        });
        function success(response) {
            $('#submit-button').prop('disabled', false);  // Re-enable the submit button
            $('#submit-spinner').hide();  // Hide the spinner
            if (response.status) {
                alert(JSON.stringify(response));
                var newDocId = response.doc_id;
                $('#add-document-modal').modal('hide');
                // refresh the document list
                loadDocuments(false)
                    .done(function(){setActiveDoc(newDocId);})
                    .fail(function(){alert(response.error);})
                // set the new document as the current document
                
            } else {
                alert(response.error);
            }
        }
        function failure(response) {
            $('#submit-button').prop('disabled', false);  // Re-enable the submit button
            $('#submit-spinner').hide();  // Hide the spinner
            alert('Error: ' + response.responseText);
            $('#add-document-modal').modal('hide');
        }
    
        function uploadFile(file) {
            var formData = new FormData();
            formData.append('pdf_file', file);
            $('#submit-button').prop('disabled', true);  // Disable the submit button
            $('#submit-spinner').show();  // Display the spinner
            fetch('/upload_pdf', { 
                method: 'POST', 
                body: formData
            })
            .then(response => response.json())
            .then(success)
            .catch(failure);
        }
    
        document.getElementById('file-upload-button').addEventListener('click', function() {
            document.getElementById('pdf-file').click();
        });
        
        // Handle file selection
        document.getElementById('pdf-file').addEventListener('change', function(e) {
            var file = e.target.files[0];  // Get the selected file
            if (file && file.type === 'application/pdf') {
                uploadFile(file);  // Call the file upload function
            }
        });
    
        var dropArea = document.getElementById('drop-area');
        dropArea.addEventListener('dragover', function(e) {
            e.preventDefault();  // Prevent the default dragover behavior
            this.style.backgroundColor = '#eee';  // Change the color of the drop area
        }, false);
    
        dropArea.addEventListener('dragleave', function(e) {
            this.style.backgroundColor = 'transparent';  // Change the color of the drop area back to its original color
        }, false);
    
        dropArea.addEventListener('drop', function(e) {
            e.preventDefault();  // Prevent the default drop behavior
            this.style.backgroundColor = 'transparent';  // Change the color of the drop area back to its original color
            
            // Check if the dropped item is a file
            if (e.dataTransfer.items) {
                for (var i = 0; i < e.dataTransfer.items.length; i++) {
                    // If the dropped item is a file and it's a PDF
                    if (e.dataTransfer.items[i].kind === 'file' && e.dataTransfer.items[i].type === 'application/pdf') {
                        var file = e.dataTransfer.items[i].getAsFile();
                        uploadFile(file);  // Call the file upload function
                    }
                }
            }
        }, false);
        $('#add-document-form').on('submit', function(event) {
            event.preventDefault();  // Prevents the default form submission action
            var pdfUrl = $('#pdf-url').val();
            if (pdfUrl) {
                $('#submit-button').prop('disabled', true);  // Disable the submit button
                $('#submit-spinner').show();  // Display the spinner
                apiCall('/index_document', 'POST', { pdf_url: pdfUrl }, useFetch = false)
                    .done(success)
                    .fail(failure);
            } else {
                alert('Please enter a PDF URL');
            }
        });
    }


    
    initialiseKeyStore();
    showUserName();
    loadDocuments();
    initSearch("searchBox");
    setupAskQuestionsView();
    setupPDFModalSubmit();
    
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
        $('#details-content').show();
        $('#pdf-content').hide();
        loadCitationsAndReferences();
    });
    
    $('#pdf-tab').on('shown.bs.tab', function (e) {
        // Clear the details viewer
        $('#details-content').hide();
        $('#pdf-content').show();

        // Display the PDF when the PDF tab is activated
//         showPDF(pdfUrl);  // replace pdfUrl with the URL of your PDF
    });
    
    $('#hide-sidebar').on('click', toggleSidebar);
    $('#show-sidebar').on('click', toggleSidebar);
    
    document.getElementById('toggle-tab-content').addEventListener('click', function() {
        var tabContent = document.querySelector('.tab-content');
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
    
    $('#documents').on('click', '.list-group-item', function(e) {
        e.preventDefault();
        var docId = $(this).attr('data-doc-id');
        $('.view').empty();
        setActiveDoc(docId);
    });

});
