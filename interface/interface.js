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
    
    
    
    

    function toggleSidebar() {
        function getActiveTabName() {
            var activeTab = $('#pdf-details-tab .nav-link.active').attr('id');
            return activeTab;
        }
        var activeTabName = getActiveTabName();

        if (activeTabName === 'assistant-tab' || activeTabName === 'search-tab' || activeTabName === 'finchat-tab') {
            var sidebar = $('#chat-assistant-sidebar');
            var otherSidebar = $('#doc-keys-sidebar');
            var contentCol = $('#chat-assistant');
        } else if ((activeTabName === 'review-assistant-tab') || (activeTabName === 'pdf-tab') || (activeTabName === 'details-tab') || (activeTabName === 'details-tab')) {
            var sidebar = $('#doc-keys-sidebar');
            var otherSidebar = $('#chat-assistant-sidebar');
            var contentCol = $('#content-col');
        }
        if (sidebar.is(':visible')) {
            // If the sidebar is currently visible, hide it
            sidebar.addClass('d-none');

            // Adjust the width of the content column
            contentCol.removeClass('col-md-10').addClass('col-md-12');
        } else {
            // If the sidebar is currently hidden, show it
            sidebar.removeClass('d-none');
            otherSidebar.addClass('d-none');

            // Adjust the width of the content column
            contentCol.removeClass('col-md-12').addClass('col-md-10');
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
                showPDF(data.source, "pdf-content");
                
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
                        firstDocId = activeDocId || doc.doc_id
                        setActiveDoc(firstDocId);
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

    
    showUserName();
    
    function run_once() {
        var is_it_run = false
        return function() {
            if (!is_it_run) {
                loadDocuments();
                initSearch("searchBox");
                setupAskQuestionsView();
                setupPDFModalSubmit();
                initiliseNavbarHiding();
                is_it_run = true
            }
        } 
    }
    init_once_pdf_tab = run_once()
    
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
        $("#chat-pdf-content").addClass('d-none');

        loadCitationsAndReferences();
        pdfTabIsActive();
        toggleSidebar();
    });

    $('#review-assistant-tab').on('shown.bs.tab', function (e) {
        // Call the '/get_paper_details' API to fetch the data
        $('#pdf-view').hide();
        $('#references-view').hide();
        $('#review-assistant-view').show();
        $('#chat-assistant-view').hide();
        $("#chat-pdf-content").addClass('d-none');
        pdfTabIsActive();
        toggleSidebar();
        
        
    });
    
    $('#pdf-tab').on('shown.bs.tab', function (e) {
        // Clear the details viewer
        $('#review-assistant-view').hide();
        $('#references-view').hide();
        $('#pdf-view').show();
        $('#chat-assistant-view').hide();
        $("#chat-pdf-content").addClass('d-none');
        pdfTabIsActive();
        toggleSidebar();
        init_once_pdf_tab();
        
        
    });
    

    $('#assistant-tab').on('click', function () { 
        $("#chat-pdf-content").addClass('d-none'); 
    })
    $('#search-tab').on('click', function () { $("#chat-pdf-content").addClass('d-none'); })
    $('#finchat-tab').on('click', function () { $("#chat-pdf-content").addClass('d-none'); })
    $('#assistant-tab').on('shown.bs.tab', function (e) {
        currentDomain["domain"] = "assistant";
        $("#field-selector").val("None");
        $('#permanentText').show();
        $('#linkInput').show();
        $('#searchInput').show();
        $("#field-selector").parent().show();
        $("#chat-options-assistant-use-google-scholar").parent().show();
        $("#chat-options-assistant-use-multiple-docs-checkbox").parent().show();
        $("#chat-options-assistant-tell-me-more-checkbox").parent().show();
        activateChatTab();
    });
    $('#search-tab').on('shown.bs.tab', function (e) {
        currentDomain["domain"] = "search";
        $("#field-selector").val("None");
        activateChatTab();
        $('#permanentText').hide();
        $('#linkInput').hide();
        $('#searchInput').hide();
        
        $("#field-selector").parent().show();
        $("#chat-options-assistant-use-google-scholar").parent().show();
        $("#chat-options-assistant-use-multiple-docs-checkbox").parent().hide();
        $("#chat-options-assistant-tell-me-more-checkbox").parent().show();
    });

    $('#finchat-tab').on('shown.bs.tab', function (e) {
        currentDomain["domain"] = "finchat";
        activateChatTab();
        $('#linkInput').hide();
        $('#searchInput').hide();
        $('#permanentText').hide();
        $("#field-selector").val("Finance");
        $("#field-selector").parent().hide();
        $("#chat-options-assistant-use-google-scholar").parent().hide();
        $("#chat-options-assistant-use-google-scholar").prop('checked', false);
        $("#chat-options-assistant-use-multiple-docs-checkbox").parent().hide();
        $("#chat-options-assistant-use-multiple-docs-checkbox").prop('checked', false);
        $("#chat-options-assistant-tell-me-more-checkbox").parent().hide();
        $("#chat-options-assistant-tell-me-more-checkbox").prop('checked', false);
        
    });
    
    $('#show-sidebar').on('click', toggleSidebar);
    $('#show-sidebar').on('click', function () { $("#chat-pdf-content").addClass('d-none');});
    
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

    // document.getElementById('review-assistant-tab').addEventListener('click', function() {
    //     var tabContent = document.querySelector('.tab-content');
    //     tabContent.style.display = 'block';
    // });

    $(document).on('click', '.copy-code-btn', function() {
        copyToClipboard($(this), undefined,  "code");
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

    $('#search-tab').trigger('shown.bs.tab');
    $("a#search-tab.nav-link").addClass('active');
    $("a#pdf-tab.nav-link").removeClass('active');
    pdfTabIsActive();
    // $("#assistant-tab").tigger('click');
    // $("a#assistant-tab.nav-link").trigger('click');

});
