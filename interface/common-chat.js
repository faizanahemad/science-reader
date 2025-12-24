// Global variables to track streaming controllers
var currentStreamingController = null;
var currentHintStreamingController = null;
var currentSolutionStreamingController = null;
var currentDoubtStreamingController = null;

var ConversationManager = {
    activeConversationId: null,
    getActiveConversation: function () {
        return this.activeConversationId;
    },

    listConversations: function () {
        // The code to list conversations goes here...
    },

    createConversation: function () {
        // var domain = $("#field-selector").val();
        // if (domain === 'None') {
        //     domain = currentDomain['domain']
        // }
        $.ajax({
            url: '/create_conversation/' + currentDomain['domain'],
            type: 'POST',
            success: function (conversation) {
                $('#linkInput').val('')
                $('#searchInput').val('')
                // Add new conversation to the list
                loadConversations(true).done(function () {
                    // Set the new conversation as the active conversation and highlight it
                    ConversationManager.setActiveConversation(conversation.conversation_id);
                });
            }
        });
    },

    deleteConversation: function (conversationId) {
        $.ajax({
            url: '/delete_conversation/' + conversationId,
            type: 'DELETE',
            success: function (result) {
                // Remove the conversation from the sidebar
                $("a[data-conversation-id='" + conversationId + "']").remove();
                // If the deleted conversation is the active conversation
                if (ConversationManager.activeConversationId == conversationId) {
                    // Set the first conversation as the active conversation
                    var firstConversationId = $('#conversations a:first').attr('data-conversation-id');
                    // TODO: if there are no conversations, then hide the chat view
                    ConversationManager.setActiveConversation(firstConversationId);
                }
            }
        });
    },

    cloneConversation: function (conversationId) {
        return $.ajax({
            url: '/clone_conversation/' + conversationId,
            type: 'POST',
            success: function (result) {
                
            }
        });
    },

    statelessConversation: function (conversationId) {
        return $.ajax({
            url: '/make_conversation_stateless/' + conversationId,
            type: 'DELETE',
            success: function (result) {
                // show a small modal that conversation is now stateless and will be deleted on next reload
                if (currentDomain['domain'] === 'assistant' || currentDomain['domain'] === 'finance') {
                    $('#stateless-conversation-modal').modal('show');
                }
            },
            error: function (result) {
                alert('Error: ' + result.responseText);
            }
        });
    },

    statefulConversation: function (conversationId, copy_model_or_state_modal = true) {
        return $.ajax({
            url: '/make_conversation_stateful/' + conversationId,
            type: 'PUT',
            success: function (result) {
                // show a small modal that conversation is now stateless and will be deleted on next reload
                if (copy_model_or_state_modal) {
                    $('#stateful-conversation-modal').modal('show');
                } else {
                    $('#clipboard-modal').modal('show');
                }
                
            },
            error: function (result) {
                alert('Error: ' + result.responseText);
            }
        });
    },

    saveMemoryPadText: function (text) {
        activeConversationId = this.activeConversationId
        return $.ajax({
            url: '/set_memory_pad/' + activeConversationId,
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ 'text': text }),  
            success: function (result) {
                $('#memory-pad-text').val(text);
            },
            error: function (result) {
                alert('Error: ' + result.responseText);
            }
        });
    },

    saveMessageEditText: function (text, message_id, index, card) {
        activeConversationId = this.activeConversationId
        return $.ajax({
            url: '/edit_message_from_conversation/' + activeConversationId + '/' + message_id + '/' + index,
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ 'text': text }),  
            success: function (result) {
                // Rerender the card
                answer = text
                answerParagraph = card.find('.actual-card-text').last();
                if (answerParagraph) {
                    renderInnerContentAsMarkdown(answerParagraph, function () {
                        if (answerParagraph.text().length > 300) {
                            // showMore(null, text = null, textElem = answerParagraph, as_html = true, show_at_start = true);
                        }
                    }, continuous = false, html = answer);
                    initialiseVoteBank(card, `${answer}`, contentId = null, activeDocId = ConversationManager.activeConversationId);
                }
            },
            error: function (result) {
                alert('Error: ' + result.responseText);
            }
        });
    },

    convertToTTSAutoPlay: function (text, messageId, messageIndex, cardElem, recompute = false, shortTTS = false, podcastTTS = false) {
        const conversationId = this.activeConversationId;
        // Check if the browser supports MediaSource
        if (!window.MediaSource) {
            console.warn('MediaSource not supported in this browser. Fallback to non-streaming approach.');
            // Fallback: just call the non-streaming approach
            return this.convertToTTSNoAutoPlay(text, messageId, messageIndex, cardElem, recompute, shortTTS, podcastTTS);
        }
        
        // We'll stream TTS using fetch and ReadableStream, appending to a MediaSource.
        return new Promise((resolve, reject) => {
            // 1) Create MediaSource + URL
            const mediaSource = new MediaSource();
            const objectUrl = URL.createObjectURL(mediaSource);

            // 2) We set up a handler for when the MediaSource is "open"
            mediaSource.addEventListener('sourceopen', () => {
                let sourceBuffer;
                try {
                    // We'll parse an audio/mpeg SourceBuffer
                    sourceBuffer = mediaSource.addSourceBuffer('audio/mpeg');
                } catch (e) {
                    console.error('Error adding source buffer:', e);
                    reject(e);
                    return;
                }

                // Keep a queue of chunks so we only append one at a time
                const chunkQueue = [];
                let appending = false;

                // We append the chunk at the front of chunkQueue
                function appendNextChunk() {
                    if (appending || !chunkQueue.length) return;
                    appending = true;
                    const chunk = chunkQueue.shift();
                    sourceBuffer.appendBuffer(chunk);
                }

                // Called when the update (appendBuffer) ends
                sourceBuffer.addEventListener('updateend', () => {
                    appending = false;
                    // Attempt to append the next chunk if available
                    if (chunkQueue.length) {
                        appendNextChunk();
                    }
                });

                // 3) fetch in streaming mode
                fetch(`/tts/${conversationId}/${messageId}`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        text: text,
                        message_id: messageId,
                        message_index: messageIndex,
                        recompute: recompute,
                        streaming: true,
                        shortTTS: shortTTS,
                        podcastTTS: podcastTTS
                    })
                }).then(response => {
                    if (!response.ok) {
                        throw new Error(`Network response was not ok (status ${response.status})`);
                    }
                    return response.body; // get ReadableStream
                }).then(stream => {
                    // 4) Read from the stream in chunks
                    const reader = stream.getReader();

                    function readNext() {
                        reader.read().then(({done, value}) => {
                            if (done) {
                                // End of stream
                                try {
                                    // Indicate the entire stream is done
                                    mediaSource.endOfStream();
                                } catch (e) {
                                    console.warn('endOfStream error:', e);
                                }
                                return;
                            }

                            // queue chunk
                            chunkQueue.push(value);
                            appendNextChunk(); // attempt to append if buffer is free

                            // keep reading
                            readNext();
                        }).catch(err => {
                            console.error('Stream read error:', err);
                            reject(err);
                        });
                    }

                    readNext();
                }).catch(err => {
                    console.error('fetch error for streaming audio:', err);
                    reject(err);
                });
            });

            // 5) Resolve the final URL for the caller to set up <audio src=...>
            //    Usually we can resolve right away, as the audio can begin playing
            //    as soon as the MediaSource is open. Attaching the URL is enough.
            resolve(objectUrl);
        });
    },

    // APPROACH B: Fully user-initiated. We set audio.src but let the user press play.
    convertToTTSProgressiveDownload: function (text, messageId, messageIndex, cardElem, recompute = false, shortTTS = false, podcastTTS = false) {
        const activeConversationId = this.activeConversationId;
        const audio = new Audio();
        let objectUrl = null;
        let enoughDataLoaded = false; // optional to track if there's enough data to play

        return new Promise((resolve, reject) => {
            const xhr = new XMLHttpRequest();
            xhr.open('POST', '/tts/' + activeConversationId + '/' + messageId, true);
            xhr.responseType = 'blob';
            xhr.setRequestHeader('Content-Type', 'application/json');

            xhr.onprogress = function(event) {
                // We can set src as soon as it has some minimal threshold to ensure audio is recognized
                if (!enoughDataLoaded && xhr.response && xhr.response.size > 32768) {
                    if (objectUrl) URL.revokeObjectURL(objectUrl);
                    objectUrl = URL.createObjectURL(xhr.response);
                    audio.src = objectUrl;
                    // We do NOT call audio.play() here
                    enoughDataLoaded = true;
                    // Resolve so that the UI can display an audio element
                    resolve(objectUrl);
                }
            };

            xhr.onload = function() {
                if (xhr.status === 200) {
                    if (!enoughDataLoaded) {
                        if (objectUrl) URL.revokeObjectURL(objectUrl);
                        objectUrl = URL.createObjectURL(xhr.response);
                        audio.src = objectUrl;
                    }
                    // No forced playback
                    resolve(objectUrl);
                } else {
                    reject(new Error('Failed to load audio'));
                }
            };
            
            xhr.onerror = function() {
                reject(new Error('Network error occurred'));
            };

            xhr.send(JSON.stringify({
                text,
                message_id: messageId,
                message_index: messageIndex,
                recompute,
                streaming: true,
                shortTTS: shortTTS,
                podcastTTS: podcastTTS
            }));
        });
    },

    convertToTTS: function (text, messageId, messageIndex, cardElem, recompute = false, autoPlay = false, shortTTS = false, podcastTTS = false) {
        if (autoPlay) {
            return this.convertToTTSAutoPlay(text, messageId, messageIndex, cardElem, recompute, shortTTS, podcastTTS);
        } else {
            return this.convertToTTSProgressiveDownload(text, messageId, messageIndex, cardElem, recompute, shortTTS, podcastTTS);
        }
    },

    fetchMemoryPad: function () {
        activeConversationId = this.activeConversationId
        return $.ajax({
            url: '/fetch_memory_pad/' + activeConversationId,
            type: 'GET',
            success: function (result) {
                $('#memory-pad-text').val(result.text);
            }
        });
    },

    getConversationDetails: function () {
        conversationId = this.activeConversationId
        return $.ajax({
            url: '/get_conversation_details/' + conversationId,
            type: 'GET',
            success: function (result) {
                return result;
            },
            error: function (result) {
                alert('Error: ' + result.responseText);
            }
        });
    },

    getConversationHistory: function () {
        conversationId = this.activeConversationId
        return $.ajax({
            url: '/get_conversation_history/' + conversationId,
            type: 'GET',
            success: function (result) {
                return result;
            },
            error: function (result) {
                alert('Error: ' + result.responseText);
            }
        });

    },

    setActiveConversation: function (conversationId) {
        this.activeConversationId = conversationId;
        updateUrlWithConversationId(conversationId);
        // Load and render the messages in the active conversation, clear chat view
        ChatManager.listMessages(conversationId).done(function (messages) {
            ChatManager.renderMessages(conversationId, messages, true);
            // REMOVED: Auto-scroll to top when loading conversation - was interrupting user reading
            // $(document).scrollTop(0);
            // $(window).scrollTop(0);
            $('#messageText').focus();
            $("#show-sidebar").focus();
            if (window.innerWidth < 768) { // Only trigger on mobile screens
                $('#show-sidebar').click();
            }
            

        });
        this.getConversationDetails().done(function (conversationDetails) {
            currentDomain["manual_domain_change"] = false;
            if (conversationDetails.domain) {
                domain = conversationDetails.domain;
                if (domain !== currentDomain["domain"]) {
                    for (var i = 0; i < allDomains.length; i++) {
                        $('a#' + allDomains[i] + '-tab').removeClass('active');
                    }

                    active_tab = domain + '-tab';
                    $('#' + active_tab).trigger('shown.bs.tab');
                    $('a#' + active_tab).addClass('active');
                    // $('#' + active_tab).trigger('click');
                    
                    
                    

                    
                }
            }
        });
        this.fetchMemoryPad().fail(function () {
            alert('Error fetching memory pad');
        });
        ChatManager.listDocuments(conversationId).done(function (documents) {
            ChatManager.renderDocuments(conversationId, documents);
        });
        ChatManager.setupAddDocumentForm(conversationId);
        ChatManager.setupDownloadChatButton(conversationId);
        ChatManager.setupShareChatButton(conversationId);
        highLightActiveConversation(conversationId);
        // REMOVED: Auto-scroll to bottom on conversation loading - was interrupting user reading
        // var chatView = $('#chatView');
        // chatView.scrollTop(chatView.prop('scrollHeight'));
        // setTimeout(function () {
        //     chatView.scrollTop(chatView.prop('scrollHeight'));
        // }, 150);
    }

};

ConversationManager.createConversation = function() {
    WorkspaceManager.createConversationInCurrentWorkspace();
};

/**
 * Detects the last valid breakpoint in text and returns sections before and after it.
 * 
 * Protected environments (no breaks inside):
 * - Code blocks (between triple backticks ```)
 * - Math display blocks (between $$ delimiters)
 * - Details elements (between <details> and </details> tags)
 * - Inline math ($...$) within paragraphs
 * 
 * Valid breakpoints (in priority order):
 * - Before markdown headers (# ## ###)
 * - After horizontal rules (---)
 * - Between paragraphs (double newlines)
 * - After lists and blockquotes
 * 
 * @param {string} text - The text to analyze for breakpoints
 * @returns {Object} Result containing breakpoint information
 */
function getTextAfterLastBreakpoint(text) {
    // Split text into lines for analysis
    let lines = text.split('\n');
    let lastBreakpointIndex = -1;
    let breakpointType = null;
    
    // Track protected environments
    let inCodeBlock = false;
    let inMathBlock = false;
    let inDetailsBlock = false;
    let detailsDepth = 0;
    
    // Track context for better breakpoint decisions
    let inList = false;
    let inBlockquote = false;
    let mathBlockStart = -1;
    
    // Analyze each line to find valid breakpoints
    for (let i = 0; i < lines.length - 1; i++) {
        const currentLine = lines[i];
        const trimmedLine = currentLine.trim();
        const nextLine = lines[i + 1] || '';
        const trimmedNext = nextLine.trim();
        
        // Check for code block boundaries
        if (trimmedLine.startsWith('```')) {
            inCodeBlock = !inCodeBlock;
            continue;
        }
        
        // Skip if we're inside a code block
        if (inCodeBlock) continue;
        
        // Check for math block boundaries ($$)
        // Count $$ occurrences in the line
        const doubleDollarCount = (trimmedLine.match(/\$\$/g) || []).length;
        
        // Handle math blocks that span multiple lines
        if (doubleDollarCount % 2 === 1) {
            // Odd number means we're toggling math block state
            inMathBlock = !inMathBlock;
            if (inMathBlock) {
                mathBlockStart = i;
            }
        } else if (doubleDollarCount > 0 && doubleDollarCount % 2 === 0) {
            // Even number of $$ means complete math expressions on one line
            // This line contains complete math, safe to break after it
        }
        
        // Skip if we're inside a math block
        if (inMathBlock) continue;
        
        // Check for details element boundaries
        if (trimmedLine.includes('<details')) {
            detailsDepth++;
            inDetailsBlock = detailsDepth > 0;
        }
        if (trimmedLine.includes('</details>')) {
            detailsDepth = Math.max(0, detailsDepth - 1);
            inDetailsBlock = detailsDepth > 0;
        }
        
        // Skip if we're inside a details block
        if (inDetailsBlock) continue;
        
        // Track list context
        const isListItem = /^[\s]*[-*+]\s/.test(currentLine) || /^[\s]*\d+\.\s/.test(currentLine);
        const isIndentedLine = /^[\s]{2,}/.test(currentLine) && trimmedLine !== '';
        
        if (isListItem) {
            inList = true;
        } else if (trimmedLine === '' && inList && !isIndentedLine) {
            // Empty line after list (and not indented continuation) ends the list
            inList = false;
            // This is a good breakpoint - after a list
            lastBreakpointIndex = i;
            breakpointType = "after-list";
        }
        
        // Track blockquote context
        const wasInBlockquote = inBlockquote;
        inBlockquote = trimmedLine.startsWith('>');
        
        // Only look for breakpoints if not in any protected environment
        if (!inCodeBlock && !inMathBlock && !inDetailsBlock && !inList) {
            
            // Priority 1: Before headers (most significant break)
            if (trimmedLine === '' && 
                (trimmedNext.startsWith('# ') || 
                 trimmedNext.startsWith('## ') || 
                 trimmedNext.startsWith('### '))) {
                // Only use as breakpoint if we have enough content before it
                if (i > 2) {
                    lastBreakpointIndex = i;
                    breakpointType = "before-header";
                }
            }
            
            // Priority 2: After horizontal rules
            else if (trimmedLine === '---' && i > 0 && lines[i - 1].trim() === '') {
                lastBreakpointIndex = i + 1;
                breakpointType = "after-horizontal-rule";
            }
            
            // Priority 3: After blockquotes
            else if (wasInBlockquote && !inBlockquote && trimmedLine === '') {
                lastBreakpointIndex = i;
                breakpointType = "after-blockquote";
            }
            
            // Priority 4: Between paragraphs (double newline)
            else if (trimmedLine === '' && trimmedNext === '') {
                // Additional check: make sure the previous line isn't math or code
                const prevLine = i > 0 ? lines[i - 1].trim() : '';
                const isAfterMath = prevLine.includes('$$') || prevLine.endsWith('$');
                const isBeforeMath = i + 2 < lines.length && 
                    (lines[i + 2].trim().startsWith('$$') || lines[i + 2].trim().startsWith('$'));
                
                // Don't break right before or after math blocks
                if (!isAfterMath && !isBeforeMath && i < lines.length - 3) {
                    lastBreakpointIndex = i;
                    breakpointType = "paragraph-break";
                }
            }
        }
    }
    
    // Validate unclosed structures
    const codeBlockCount = (text.match(/```/g) || []).length;
    const hasUnclosedCodeBlock = codeBlockCount % 2 !== 0;
    
    // More sophisticated math block detection
    const mathBlockMatches = text.match(/\$\$/g) || [];
    const hasUnclosedMathBlock = mathBlockMatches.length % 2 !== 0;
    
    const detailsOpenCount = (text.match(/<details[^>]*>/g) || []).length;
    const detailsCloseCount = (text.match(/<\/details>/g) || []).length;
    const hasUnclosedDetails = detailsOpenCount > detailsCloseCount;
    
    // Don't create breakpoints if we have unclosed structures
    if (hasUnclosedCodeBlock || hasUnclosedMathBlock || hasUnclosedDetails) {
        return { 
            hasBreakpoint: false, 
            textAfterBreakpoint: text,
            reason: `Unclosed structure: ${hasUnclosedCodeBlock ? 'code' : hasUnclosedMathBlock ? 'math' : 'details'}`
        };
    }
    
    // If we found a valid breakpoint
    if (lastBreakpointIndex !== -1) {
        const beforeLines = lines.slice(0, lastBreakpointIndex);
        const afterLines = lines.slice(lastBreakpointIndex);
        
        // Minimum content requirements
        const MIN_CHARS_BEFORE = 100;  // At least 100 characters before break
        const MIN_CHARS_AFTER = 50;    // At least 50 characters after break
        
        const textBefore = beforeLines.join('\n').trim();
        const textAfter = afterLines.join('\n').trim();
        
        if (textBefore.length < MIN_CHARS_BEFORE || textAfter.length < MIN_CHARS_AFTER) {
            return {
                hasBreakpoint: false,
                textAfterBreakpoint: text,
                reason: 'Insufficient content for breakpoint'
            };
        }
        
        console.log(`Found breakpoint at line ${lastBreakpointIndex} (type: ${breakpointType})`);
        
        return {
            hasBreakpoint: true,
            textBeforeBreakpoint: beforeLines.join('\n'),
            textAfterBreakpoint: afterLines.join('\n'),
            breakpointType: breakpointType
        };
    }
    
    // No breakpoint found
    return {
        hasBreakpoint: false,
        textAfterBreakpoint: text
    };
}

function renderStreamingResponse(streamingResponse, conversationId, messageText, history_message_ids) {
    // Remove any existing suggestions when starting a new response
    $('#chatView .next-question-suggestions').remove();
    
    // Show stop button and hide send button
    $('#stopResponseButton').show();
    $('#sendMessageButton').hide();
    
    var reader = streamingResponse.body.getReader();
    var decoder = new TextDecoder();
    let buffer = '';
    let card = null;
    let answerParagraph = null;
    let elem_to_render = null;
    var content_length = 0;
    var answer = ''
    var rendered_answer = ''
    var response_message_id = null;
    var user_message_id = null;
    var isCancelled = false;
    
    // Store the reader for potential cancellation
    currentStreamingController = {
        reader: reader,
        conversationId: conversationId,
        cancel: function() {
            isCancelled = true;
            reader.cancel();
        }
    };
    
    // Timer for URL update (same as in renderMessages)
    let focusTimer = null;
    let currentFocusedMessageId = null;
    let streamingObserver = null;
    
    // Track if we are inside a code block
    var insideCodeBlock = false;
    // Keep track of sections for rendering
    var sectionCount = 0;
    // Slide streaming state
    var slideCollecting = false;
    var slideBuffer = '';
    var slideJustCompleted = false;

    // Function to handle message focus and URL update (same as in renderMessages)
    function handleMessageFocus(messageId, convId) {
        // Don't handle focus if message ID is not available yet
        if (!messageId) {
            return;
        }
        
        // Clear existing timer if any
        if (focusTimer) {
            clearTimeout(focusTimer);
        }
        
        messageIdInUrl = getMessageIdFromUrl();
        // Don't restart timer if same message is already focused
        if (currentFocusedMessageId === messageId && messageIdInUrl === messageId) {
            return;
        }
        
        currentFocusedMessageId = messageId;
        
        // Set new timer for 5 seconds
        focusTimer = setTimeout(function() {
            updateUrlWithMessageId(convId, messageId);
            focusTimer = null;
        }, 1000);
    }
    
    // Function to set up event handlers for the streaming card
    function setupStreamingCardEventHandlers(cardElement, messageId) {
        // Add click event handler
        cardElement.off('click').on('click', function(e) {
            // Don't trigger on button clicks, checkboxes, or dropdown elements
            if ($(e.target).closest('.delete-message-button, .history-message-checkbox, .move-message-up-button, .move-message-down-button, .show-doubts-button, .ask-doubt-button, .copy-btn-header, .dropdown, .dropdown-menu, .dropdown-item, [data-toggle="dropdown"]').length > 0) {
                return;
            }
            
            handleMessageFocus(messageId, conversationId);
        });
        
        // Add text selection event handler
        cardElement.off('selectstart mouseup').on('selectstart mouseup', function(e) {
            // Don't trigger on button clicks, checkboxes, or dropdown elements
            if ($(e.target).closest('.delete-message-button, .history-message-checkbox, .move-message-up-button, .move-message-down-button, .show-doubts-button, .ask-doubt-button, .copy-btn-header, .dropdown, .dropdown-menu, .dropdown-item, [data-toggle="dropdown"]').length > 0) {
                return;
            }
            
            // Check if text is actually selected
            setTimeout(function() {
                const selection = window.getSelection();
                if (selection && selection.toString().trim().length > 0) {
                    handleMessageFocus(messageId, conversationId);
                }
            }, 10);
        });
        
        // Add focus event handler for keyboard navigation
        cardElement.off('focus focusin').on('focus focusin', function(e) {
            // Don't trigger on button clicks, checkboxes, or dropdown elements
            if ($(e.target).closest('.delete-message-button, .history-message-checkbox, .move-message-up-button, .move-message-down-button, .show-doubts-button, .ask-doubt-button, .copy-btn-header, .dropdown, .dropdown-menu, .dropdown-item, [data-toggle="dropdown"]').length > 0) {
                return;
            }
            
            handleMessageFocus(messageId, conversationId);
        });
        
        
        // Store observer for cleanup if needed
        if (!window.messageObservers) {
            window.messageObservers = [];
        }
    }

    var rendered_till_now = ''
    var math_elems_to_render = new Set();
    var beforeElem = null;
    var afterElem = null;

    async function read() {
        try {
            const { value, done } = await reader.read();

            if (isCancelled || done) {
                // Reset UI state
                $('#messageText').prop('working', false);
                $('#stopResponseButton').hide();
                $('#sendMessageButton').show();
                currentStreamingController = null;
                
                if (done && !isCancelled) {
                    // Continue with normal completion logic
                } else if (isCancelled) {
                    // Handle cancellation
                    var statusDiv = card.find('.status-div');
                    statusDiv.find('.status-text').html('Response cancelled by user');
                    statusDiv.find('.spinner-border').hide();
                    
                    // Hide status after a brief moment to show the cancellation message
                    setTimeout(function() {
                        statusDiv.hide();
                    }, 2000);
                    
                    console.log('Stream cancelled by user');
                    return;
                }
            }

            buffer += decoder.decode(value || new Uint8Array, { stream: !done });
            let boundary = buffer.indexOf('\n');
        // Render server message
        var serverMessage = {
            sender: 'server',
            text: ''
        };

        if (!card) {
            card = ChatManager.renderMessages(conversationId, [serverMessage], false, true, history_message_ids, true);
            // Set up initial event handlers (without message ID initially)
            setupStreamingCardEventHandlers(card, null);
        }
        while (boundary !== -1) {
            const part = JSON.parse(buffer.slice(0, boundary));
            buffer = buffer.slice(boundary + 1);
            boundary = buffer.indexOf('\n');

            // Parse and handle gamification tags before processing
            let processedText = parseGamificationTags(part['text'], card);
            part['text'] = processedText.replace(/\n/g, '  \n');
            
            // Accumulate the full answer for final use
            answer = answer + part['text'];
            // Append to rendered_answer while buffering slide content until closing tag arrives
            (function appendWithSlideBuffering(chunk) {
                var startTag = '<slide-presentation>';
                var endTag = '</slide-presentation>';
                var pos = 0;
                while (pos < chunk.length) {
                    if (slideCollecting) {
                        var endIdx = chunk.indexOf(endTag, pos);
                        if (endIdx === -1) {
                            // keep buffering until we find closing tag in future chunks
                            slideBuffer += chunk.slice(pos);
                            pos = chunk.length;
                            break;
                        } else {
                            // complete the slide buffer and append it to renderable text
                            slideBuffer += chunk.slice(pos, endIdx + endTag.length);
                            rendered_answer = rendered_answer + slideBuffer;
                            slideBuffer = '';
                            slideCollecting = false;
                            slideJustCompleted = true;
                            pos = endIdx + endTag.length;
                        }
                    } else {
                        var startIdx = chunk.indexOf(startTag, pos);
                        if (startIdx === -1) {
                            rendered_answer = rendered_answer + chunk.slice(pos);
                            pos = chunk.length;
                            break;
                        } else {
                            // append text before slide, then start collecting slide
                            if (startIdx > pos) {
                                rendered_answer = rendered_answer + chunk.slice(pos, startIdx);
                            }
                            slideCollecting = true;
                            slideBuffer = startTag;
                            pos = startIdx + startTag.length;
                        }
                    }
                }
            })(part['text']);

            // If a slide block was just completed in this chunk, force an immediate render
            if (slideJustCompleted) {
                renderInnerContentAsMarkdown(elem_to_render, null, true, rendered_answer);
                content_length = rendered_answer.length;
                rendered_till_now = rendered_till_now + rendered_answer;
                slideJustCompleted = false;
            }

            if (!answerParagraph) {
                answerParagraph = card.find('.actual-card-text').last();
                elem_to_render = answerParagraph;
            }
            var statusDiv = card.find('.status-div');
            statusDiv.show();
            statusDiv.find('.spinner-border').show();
            
            if (part['text'].includes('<answer>') && card.find("#message-render-space-md-render").length > 0) {
                elem_to_render = $(`<div class="answer section-${sectionCount}" id="actual-answer-rendering-space-${sectionCount}"></div>`);
                card.find("#message-render-space-md-render").append(elem_to_render);
                elem_to_render = card.find(`#actual-answer-rendering-space-${sectionCount}`).html('');
                elem_to_render = card.find(`#actual-answer-rendering-space-${sectionCount}`)
                beforeElem = elem_to_render;
                content_length = 0;
                rendered_answer = '';
                
                sectionCount++;
            }
            
            // Check for breakpoints in the current rendered text
            const breakpointResult = getTextAfterLastBreakpoint(rendered_answer);
            
            if (breakpointResult.hasBreakpoint) {
                // Render the current section one last time with complete content
                mathjax_elem = renderInnerContentAsMarkdown(elem_to_render,
                    callback = null, continuous = true, html = breakpointResult.textBeforeBreakpoint); // rendered_answer
                rendered_till_now = rendered_till_now + breakpointResult.textBeforeBreakpoint;
                
                // Create a new section for content after the breakpoint
                const newElem = $(`<div class="answer section-${sectionCount}" id="actual-answer-rendering-space-${sectionCount}"></div>`);
                card.find("#message-render-space-md-render").append(newElem);
                elem_to_render = card.find(`#actual-answer-rendering-space-${sectionCount}`).html('');
                elem_to_render = card.find(`#actual-answer-rendering-space-${sectionCount}`)
                beforeElem = elem_to_render;
                
                // Reset rendering for the new section
                content_length = 0;
                rendered_answer = breakpointResult.textAfterBreakpoint;
                sectionCount++;
            }
            
            // elem_to_render.append(part['text']);
            
            if ((rendered_answer.length > content_length + 50 || breakpointResult.hasBreakpoint) && !rendered_till_now.includes(rendered_answer)) {
                mathjax_elem = renderInnerContentAsMarkdown(elem_to_render,
                    callback = null, continuous = true, html = rendered_answer);
                content_length = rendered_answer.length;
                rendered_till_now = rendered_till_now + rendered_answer;
                
            }
            
            if ((part['text'].includes('</answer>')) && card.find("#message-render-space-md-render").length > 0) {
                if (elem_to_render && elem_to_render.length > 0 && rendered_answer.length > 0 && !rendered_till_now.includes(rendered_answer)) {
                    mathjax_elem = renderInnerContentAsMarkdown(elem_to_render, 
                        immediate_callback = function() {
                            elem_to_render.attr('data-fully-rendered', 'true');
                        }, 
                        continuous = false, // Use false for final rendering to ensure proper display
                        html = rendered_answer);

                    rendered_till_now = rendered_till_now + rendered_answer;
                    
                }    
                elem_to_render = $(`<div class="answer section-${sectionCount}" id="actual-answer-rendering-space-${sectionCount}"></div>`);
                card.find("#message-render-space-md-render").append(elem_to_render);
                elem_to_render = card.find(`#actual-answer-rendering-space-${sectionCount}`).html('');
                elem_to_render = card.find(`#actual-answer-rendering-space-${sectionCount}`)
                beforeElem = elem_to_render;
                sectionCount++;

                content_length = 0;
                rendered_answer = '';
                
            }
            last_rendered_answer = rendered_answer;
            last_elem_to_render = elem_to_render;
            
            var statusDiv = card.find('.status-div');
            statusDiv.find('.status-text').html(part['status']);

            if (part['message_ids']) {
                user_message_id = part['message_ids']['user_message_id']
                response_message_id = part['message_ids']['response_message_id']
                Array.from(card.find('.history-message-checkbox'))[0].setAttribute('message-id', response_message_id);
                Array.from(card.find('.history-message-checkbox'))[0].setAttribute('id', `message-checkbox-${response_message_id}`);
                last_card = $(card).prevAll('.card').first()
                Array.from(last_card.find('.history-message-checkbox'))[0].setAttribute('message-id', user_message_id);
                Array.from(last_card.find('.history-message-checkbox'))[0].setAttribute('id', `message-checkbox-${user_message_id}`);
                
                // Update the card header with message-id attribute
                card.find('.card-header').attr('message-id', response_message_id);
                card.find('.delete-message-button').attr('message-id', response_message_id);
                card.find('.show-doubts-button').attr('message-id', response_message_id);
                card.find('.ask-doubt-button').attr('message-id', response_message_id);
                card.find('.move-message-up-button').attr('message-id', response_message_id);
                card.find('.move-message-down-button').attr('message-id', response_message_id);
                
                // Re-setup event handlers now that we have the message ID
                setupStreamingCardEventHandlers(card, response_message_id);
                
                // Initialize Bootstrap 4.6 dropdowns for the streaming card
                setTimeout(function() {
                    // Bootstrap 4.6 dropdowns are initialized automatically with data-toggle="dropdown"
                    card.find('[data-toggle="dropdown"]').dropdown();
                }, 25);
            }
        }

        if (done) {
            $('#messageText').prop('working', false);
            $('#stopResponseButton').hide();
            $('#sendMessageButton').show();
            currentStreamingController = null;
            var statusDiv = card.find('.status-div');
            statusDiv.hide();
            statusDiv.find('.status-text').text('');
            statusDiv.find('.spinner-border').hide();
            statusDiv.find('.spinner-border').removeClass('spinner-border');
            console.log('Stream complete');

            // Always render the last active section once more at the end
            // This ensures that any content less than the 150 character threshold gets rendered

            var show_more_called = {value: false};
            
            function show_more() {
                if (show_more_called.value == true) {
                    return;
                }
                show_more_called.value = true;
                textElem = card.find('#message-render-space')
                console.log("Calling show_more function ...")
                // check if textElem is hidden by display: none
                
                text = card.find('#message-render-space').html()
                if (text.length == 0) {
                    textElem = card.find('#message-render-space-md-render');
                    text = card.find('#message-render-space-md-render').html();
                }
                const hasSlides = (
                    !!card.find('.slide-presentation-wrapper').length ||
                    !!card.find('.slide-external-link').length ||
                    (textElem && textElem.attr('data-has-slides') === 'true')
                );
                if (!hasSlides) {
                    toggle = showMore(card.find('.chat-card-body'), text = text, textElem = textElem, as_html = true, show_at_start = true, server_side = {
                        'message_id': response_message_id,
                    }); // index >= array.length - 2
                }
                // textElem.find('.show-more').click(toggle);
                // textElem.find('.show-more').click(toggle);
            }

            if (last_elem_to_render && last_elem_to_render.length > 0) {
                const alreadyRendered = rendered_till_now.includes(last_rendered_answer);
                
                if (!alreadyRendered) {
                    renderInnerContentAsMarkdown(last_elem_to_render, 
                        immediate_callback=function() {
                            last_elem_to_render.attr('data-fully-rendered', 'true');
                            show_more();
                            handleMessageFocus(response_message_id, conversationId);
                        }, 
                        false, // Use false for final rendering
                        last_rendered_answer);
                    
                    rendered_till_now = rendered_till_now + last_rendered_answer;
                } else {
                    // Content was already rendered, just call show_more
                    show_more();
                    handleMessageFocus(response_message_id, conversationId);
                }
            }
            else {
                if (!show_more_called.value) {
                    setTimeout(show_more, 500);
                    show_more_called.value = true;
                }
            }
            if (!show_more_called.value) {
                setTimeout(show_more, 500);
                // show_more_called.value = true;
            }
            
            // Don't re-render sections that were already properly rendered during streaming
            // Instead, only ensure the last section is fully rendered if needed
            // const lastSection = card.find(".answer, .post-answer").last();
            // if (lastSection.length > 0 && !lastSection.attr('data-fully-rendered')) {
            //     // Only render the last section if it might not be completely rendered
            //     renderInnerContentAsMarkdown(lastSection, function() {
            //         // Mark as fully rendered after completion
            //         lastSection.attr('data-fully-rendered', 'true');
            //     }, false, lastSection.html());
            // }
            
            // Set up voting mechanism
            
            
            initialiseVoteBank(card, `${answer}`, contentId = null, activeDocId = ConversationManager.activeConversationId);
            mermaid.run({querySelector: "pre.mermaid"});
            
            // Add scroll-to-top button for streamed messages
            if (card && answer.length > 300) { // Only add for longer messages
                if (typeof window.addScrollToTopButton === 'function') {
                    window.addScrollToTopButton(card, '↑ Top of Answer', 'chat-scroll-top');
                }
            }
            
            // Final setup of event handlers with the complete message ID (if available)
            if (response_message_id) {
                setupStreamingCardEventHandlers(card, response_message_id);
            }
            
            // Call next question suggestions after streaming response is complete
            setTimeout(function() {
                renderNextQuestionSuggestions(conversationId);
            }, 500);
            
            return;
        }
        
        // Recursive call to read next message part
        setTimeout(read, 10);
        
        } catch (error) {
            if (error.name === 'AbortError') {
                console.log('Stream was cancelled');
                // Update status for cancellation
                if (card) {
                    var statusDiv = card.find('.status-div');
                    statusDiv.find('.status-text').html('Response cancelled by user');
                    statusDiv.find('.spinner-border').hide();
                    
                    // Hide status after a brief moment
                    setTimeout(function() {
                        statusDiv.hide();
                    }, 2000);
                }
            } else {
                console.error('Error reading stream:', error);
                // Update status for error
                if (card) {
                    var statusDiv = card.find('.status-div');
                    statusDiv.find('.status-text').html('Error occurred during streaming');
                    statusDiv.find('.spinner-border').hide();
                    
                    // Hide status after a brief moment
                    setTimeout(function() {
                        statusDiv.hide();
                    }, 3000);
                }
            }
            
            // Reset UI state
            $('#messageText').prop('working', false);
            $('#stopResponseButton').hide();
            $('#sendMessageButton').show();
            currentStreamingController = null;
        }
    }

    read();
}

// Add stop response function
function stopCurrentResponse() {
    if (currentStreamingController) {
        // Provide immediate visual feedback
        var card = $('#chatView .card').last();
        if (card.length > 0) {
            var statusDiv = card.find('.status-div');
            statusDiv.find('.status-text').html('Stopping response...');
            statusDiv.find('.spinner-border').hide();
        }
        
        // Send cancellation request to server
        fetch(`/cancel_response/${currentStreamingController.conversationId}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            }
        }).then(response => {
            if (response.ok) {
                console.log('Cancellation request sent successfully');
                // Update status to show successful cancellation
                if (card.length > 0) {
                    var statusDiv = card.find('.status-div');
                    statusDiv.find('.status-text').html('Response cancelled by user');
                }
            } else {
                console.error('Failed to send cancellation request');
                // Update status to show error
                if (card.length > 0) {
                    var statusDiv = card.find('.status-div');
                    statusDiv.find('.status-text').html('Failed to cancel response');
                }
            }
        }).catch(error => {
            console.error('Error sending cancellation request:', error);
            // Update status to show error
            if (card.length > 0) {
                var statusDiv = card.find('.status-div');
                statusDiv.find('.status-text').html('Error cancelling response');
            }
        });
        
        // Cancel the stream reading
        currentStreamingController.cancel();
    }
}

// Add stop coding hint function
function stopCodingHint() {
    if (currentHintStreamingController) {
        // Provide immediate visual feedback
        var statusElement = $('#hint-status');
        var statusTextElement = $('#hint-status-text');
        statusElement.show();
        statusTextElement.text('Stopping hint generation...');
        
        // Send cancellation request to server
        fetch(`/cancel_coding_hint/${currentHintStreamingController.conversationId}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            }
        }).then(response => {
            if (response.ok) {
                statusTextElement.text('Hint generation cancelled by user');
                setTimeout(function() {
                    statusElement.hide();
                }, 2000);
            } else {
                statusTextElement.text('Failed to cancel hint generation');
            }
        }).catch(error => {
            statusTextElement.text('Error cancelling hint generation');
        });
        
        // Cancel the stream reading
        currentHintStreamingController.cancel();
    }
}

// Add stop coding solution function
function stopCodingSolution() {
    if (currentSolutionStreamingController) {
        // Provide immediate visual feedback
        var statusElement = $('#solution-status');
        var statusTextElement = $('#solution-status-text');
        statusElement.show();
        statusTextElement.text('Stopping solution generation...');
        
        // Send cancellation request to server
        fetch(`/cancel_coding_solution/${currentSolutionStreamingController.conversationId}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            }
        }).then(response => {
            if (response.ok) {
                statusTextElement.text('Solution generation cancelled by user');
                setTimeout(function() {
                    statusElement.hide();
                }, 2000);
            } else {
                statusTextElement.text('Failed to cancel solution generation');
            }
        }).catch(error => {
            statusTextElement.text('Error cancelling solution generation');
        });
        
        // Cancel the stream reading
        currentSolutionStreamingController.cancel();
    }
}

// Add stop doubt clearing function
function stopDoubtClearing() {
    // Check if there's actually an active streaming controller
    if (!currentDoubtStreamingController) {
        console.log('No active doubt streaming to stop');
        return;
    }
    
    console.log('Stopping doubt clearing...');
    
    // Provide immediate visual feedback - find the assistant card that's currently being streamed
    var assistantCard = $('#doubt-chat-messages .doubt-conversation-card.assistant-doubt').last();
    if (assistantCard.length > 0) {
        // Append stopping message instead of replacing content
        assistantCard.find('.card-body').append('<div class="alert alert-warning mt-2 mb-0">Stopping response...</div>');
    }
    
    // Send cancellation request to server
    fetch(`/cancel_doubt_clearing/${currentDoubtStreamingController.conversationId}`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        }
    }).then(response => {
        if (!response.ok) {
            console.error('Failed to send doubt clearing cancellation request');
        }
    }).catch(error => {
        console.error('Error sending doubt clearing cancellation request:', error);
    });
    
    // Cancel the stream reading - this will trigger the cancellation logic in renderStreamingDoubtResponse
    currentDoubtStreamingController.cancel();
}

function highLightActiveConversation(conversationId) {
    $('#conversations .list-group-item').removeClass('active');
    $('#conversations .list-group-item[data-conversation-id="' + conversationId + '"]').addClass('active');
    WorkspaceManager.highlightActiveConversation(conversationId);
}

function getMessageIdFromUrl(url) {
    const path = url ? new URL(url).pathname : window.location.pathname;
    const pathParts = path.split('/');
    
    // Remove any hash fragments from the end of the path
    const cleanPath = pathParts[pathParts.length - 1].split('#')[0];
    pathParts[pathParts.length - 1] = cleanPath;
    
    // Check if the URL contains a message ID
    // Expected format: /interface/<conversation_id>/<message_id>
    if (pathParts.length > 3 && pathParts[1] === 'interface' && pathParts[2] && pathParts[3]) {
        return pathParts[3];
    }
    return null;
}

function cleanupMessageObservers() {
    if (window.messageObservers) {
        window.messageObservers.forEach(function(observer) {
            observer.disconnect();
        });
        window.messageObservers = [];
    }
}


function updateUrlWithMessageId(conversationId, messageId) {
    // Update the URL without reloading the page
    window.history.pushState({conversationId: conversationId, messageId: messageId}, '', `/interface/${conversationId}/${messageId}`);
}


var ChatManager = {
    shownDoc: null,
    listDocuments: function (conversationId) {
        return $.ajax({
            url: '/list_documents_by_conversation/' + conversationId,
            type: 'GET'
        });
    },
    listMessages: function (conversationId) {
        return $.ajax({
            url: '/list_messages_by_conversation/' + conversationId,
            type: 'GET'
        });
    },
    deleteLastMessage: function (conversationId) {
        $('#loader').css('background-color', 'rgba(0, 0, 0, 0.1) !important');
        $('#loader').show(); 

        return $.ajax({
            url: '/delete_last_message/' + conversationId,
            type: 'DELETE',
            success: function (response) {
                // Reload the conversation
                ChatManager.listMessages(conversationId).done(function (messages) {
                    ChatManager.renderMessages(conversationId, messages, true);
                    $('#loader').hide(); 
                    // Auto-scroll after deleting last message 
                    var $chatView = $('#chatView');
                    $chatView.animate({ scrollTop: $chatView.prop("scrollHeight") }, "fast");
                    $('#messageText').focus();

                });
            }
        });
    },
    deleteDocument: function (conversationId, documentId) {
        return $.ajax({
            url: '/delete_document_from_conversation/' + conversationId + '/' + documentId,
            type: 'DELETE',
            success: function (response) {
                // Reload the conversation
                ChatManager.listDocuments(conversationId).done(function (documents) {
                    ChatManager.renderDocuments(conversationId, documents);
                });
            }
        });
    },
    setupDownloadChatButton: function (conversationId) {
        $('#get-chat-transcript').off().on('click', function () {
            window.open('/list_messages_by_conversation_shareable/' + conversationId, '_blank');
        });
    },
    setupShareChatButton: function (conversationId) {
        $('#share-chat').off().on('click', function () {
            window.open('/shared/' + conversationId, '_blank');
            var domainURL = window.location.protocol + "//" + window.location.hostname + (window.location.port ? ':' + window.location.port : '');  
            copyToClipboard(null, domainURL + '/shared/' + conversationId, "text");
            ConversationManager.statefulConversation(conversationId, false);
        });
    },
    setupAddDocumentForm: function (conversationId) {
        let doc_modal = $('#add-document-modal-chat')
        $('#add-document-button-chat').off().click(function () {
            $('#add-document-modal-chat').modal({ backdrop: 'static', keyboard: false }, 'show');
        });
        function success(response) {
            doc_modal.find('#submit-button').prop('disabled', false);  // Re-enable the submit button
            doc_modal.find('#submit-spinner').hide();  // Hide the spinner

            
            // Assuming you have a spinner element for feedback
            let progressContainer = $('#uploadProgressContainer');
            

            if (response.status) {
                ChatManager.listDocuments(conversationId)
                    .done(function (documents) {
                        doc_modal.modal('hide');
                        ChatManager.renderDocuments(conversationId, documents);
                        progressContainer.hide();
                        $('#sendMessageButton').prop('disabled', false);
                        $('#sendMessageButton').show();
                    })
                    .fail(function () {
                        doc_modal.modal('hide');
                        progressContainer.hide();
                        $('#sendMessageButton').prop('disabled', false);
                        $('#sendMessageButton').show();
                        alert(response.error);
                    })
                // set the new document as the current document

            } else {
                progressContainer.hide();
                $('#sendMessageButton').prop('disabled', false);
                $('#sendMessageButton').show();
                alert(response.error);
            }
        }
        function failure(response) {
            doc_modal.find('#submit-button').prop('disabled', false);  // Re-enable the submit button
            doc_modal.find('#submit-spinner').hide();  // Hide the spinner
            $('#sendMessageButton').prop('disabled', false);
            $('#sendMessageButton').show();
            // Assuming you have a spinner element for feedback
            let progressContainer = $('#uploadProgressContainer');
            progressContainer.hide();
            alert('Error: ' + response.responseText);
            doc_modal.modal('hide');
        }

        function uploadFile_internal(file) {
            let xhr = new XMLHttpRequest();
            var formData = new FormData();
            formData.append('pdf_file', file);
            doc_modal.find('#submit-button').prop('disabled', true);  // Disable the submit button
            doc_modal.find('#submit-spinner').show();  // Display the spinner
            
            $('#sendMessageButton').prop('disabled', true);
            $('#sendMessageButton').hide();
            let progressContainer = $('#uploadProgressContainer');
            let progressText = $('#uploadProgressText');
            progressContainer.show();
            progressText.text('0%');
            xhr.open('POST', '/upload_doc_to_conversation/' + conversationId, true);
            xhr.upload.onprogress = function (e) {
                if (e.lengthComputable) {
                    let percentComplete = Math.round((e.loaded / e.total) * 70);
                    progressText.text(percentComplete + '%'); // Update progress text
                }
            };

            intrvl = setInterval(function () {
                currentProgress = parseInt(progressText.text().replace('%', ''));
                if (currentProgress < 100 && currentProgress >= 70) {
                    progressText.text(currentProgress + 1 + '%');
                }
            }, 1000);

            xhr.onload = function () {
                
                if (xhr.status == 200) {
                    let response = JSON.parse(xhr.responseText);
                    // Handle success
                    success(response); // Make sure to define this function
                } else {
                    // Handle failure
                    failure(xhr.response); // Make sure to define this function
                }

                clearInterval(intrvl);
            };

            // Error event
            xhr.onerror = function () {
                failure(xhr.response); // Make sure to define this function
                progressContainer.hide();
                clearInterval(intrvl);
            };

            // Send the form data with the file
            xhr.send(formData);
        }

        function uploadFile(file) {
            if (isValidFileType(file)) {
                uploadFile_internal(file);  // Call the file upload function
            } else {
                console.log(`Invalid file type ${file.type}.`)
                console.log(`Invalid file type ${getFileType(file, ()=>{})}.`)
                console.log(`Invalid file type ${getMimeType(file)}.`)
                const supportedTypes = fileInput.attr('accept')
                    .replace(/, /g, ', ')
                    .replace(/application\//g, '')
                    .replace(/vnd.openxmlformats-officedocument.wordprocessingml.document/g, 'docx')
                    .replace(/vnd.openxmlformats-officedocument.spreadsheetml.sheet/g, 'xlsx')
                    .replace(/vnd.ms-excel/g, 'xls')
                    .replace(/text\//g, '')
                    .replace(/image\//g, '')
                    .replace(/audio\//g, '')
                    .replace(/video\//g, '')
                    .replace(/svg\+xml/g, 'svg');
                alert(`Invalid file type ${file.type}. Supported types are: ` + supportedTypes);
            } 
        }

        doc_modal.find('#file-upload-button').off().on('click', function () {
            doc_modal.find('#pdf-file').click();
        });

        // Handle file selection
        doc_modal.find('#pdf-file').off().on('change', function (e) {
            var file = $(this)[0].files[0];  // Get the selected file
            // check pdf or doc docx
            if (file) {
                uploadFile(file);  // Call the file upload function
            }
        });

        $('#chat-file-upload-span').off().on('click', function () {
            $('#chat-file-upload').click();
        });

        $('#chat-file-upload').off().on('change', function (e) {
            var file = e.target.files[0]; // Get the selected file
            if (file) {
                uploadFile(file); // Call the file upload function
            }
        });

        // Handle filedrop
        var fileInput = $('#chat-file-upload');
        let dropArea = doc_modal.find('#drop-area').off();
        dropArea.off('dragover').on('dragover', function (e) {
            e.preventDefault();  // Prevent the default dragover behavior
            $(this).css('background-color', '#eee');  // Change the color of the drop area
        });
        dropArea.off('dragleave').on('dragleave', function (e) {
            $(this).css('background-color', 'transparent');  // Change the color of the drop area back to its original color
        });
        dropArea.off('drop').on('drop', function (e) {
            e.preventDefault();  // Prevent the default drop behavior
            $(this).css('background-color', 'transparent');  // Change the color of the drop area back to its original color

            // Check if the dropped item is a file
            if (e.originalEvent.dataTransfer.items) {
                for (var i = 0; i < e.originalEvent.dataTransfer.items.length; i++) {
                    // If the dropped item is a file and it's a PDF, word doc docx
                    if (e.originalEvent.dataTransfer.items[i].kind === 'file') {
                        var file = e.originalEvent.dataTransfer.items[i].getAsFile();
                        uploadFile(file);
                    }
                }
            }
        });
        doc_modal.find('#add-document-form').off().on('submit', function (event) {
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

        
        // Function to check if the file type is valid  
        function isValidFileType(file) {  
            var validTypes = fileInput.attr('accept').split(', ').map(type => type.toLowerCase());  
              
            // Get file extension  
            var fileName = file.name.toLowerCase();  
            var fileExtension = fileName.substring(fileName.lastIndexOf('.'));  
              
            // MIME type from browser  
            var mimeType = (file.type || getMimeType(file) || '').toLowerCase();  
              
            // Special handling for markdown files  
            var isMarkdown = fileExtension === '.md' || fileExtension === '.markdown';  
            var isMarkdownMime = mimeType === 'text/markdown' ||   
                                mimeType === 'text/md' ||   
                                mimeType === 'text/x-markdown' || mimeType === 'application/octet-stream';  
              
            // Check if it's a valid markdown file  
            if (isMarkdown && (isMarkdownMime || mimeType === 'text/plain' || mimeType === '')) {  
                return true;  
            }  

            var audioExtensions = ['.mp3', '.mpeg', '.wav', '.wave', '.m4a', '.aac', '.flac', '.ogg', '.oga', '.opus', '.webm', '.wma', '.aiff', '.aif', '.aifc', '.mp4'];  
            var audioMimeTypes = ['audio/mpeg', 'audio/mp3', 'audio/wav', 'audio/x-wav', 'audio/webm', 'audio/ogg', 'audio/flac', 'audio/x-flac', 'audio/aac', 'audio/m4a', 'audio/x-m4a', 'audio/mp4', 'video/mp4', 'audio/opus', 'audio/x-ms-wma', 'audio/aiff'];  

            if (audioExtensions.includes(fileExtension) && (audioMimeTypes.includes(mimeType) || mimeType === '' || mimeType === 'application/octet-stream')) {  
                return true;  
            }  
              
            // Standard MIME type validation for other files  
            return validTypes.includes(mimeType);  
        } 

        $(document).off('dragover').on('dragover', function (event) {
            event.preventDefault(); // Prevent default behavior (Prevent file from being opened)  
            $(this).css('background-color', '#eee');  // Change the color of the drop area
        }); 

        $(document).off('dragleave').on('dragleave', function (e) {
            $(this).css('background-color', 'transparent');  // Change the color of the drop area back to its original color
        });

        $(document).off('drop').on('drop', function (event) {
            event.preventDefault();
            var files = event.originalEvent.dataTransfer.files;
            for (var i = 0; i < files.length; i++) {
                var file = files[i];
                uploadFile(file);  // Call the file upload function
            }
        });  
    },
    renderDocuments: function (conversation_id, documents) {
        console.log(documents);
        var chat_doc_view = $('#chat-doc-view');

        // Clear existing documents
        chat_doc_view.children('div').remove();

        // Loop through documents
        documents.forEach(function (doc, index) {
            // Create buttons for each document
            var docButton = $('<button></button>')
                .addClass('btn btn-outline-primary btn-sm mr-2 mb-1')
                .text(`#doc_${index + 1}`)
                .attr('data-doc-id', doc.doc_id)
                .attr('data-toggle', 'tooltip')
                .attr('data-trigger', 'hover')
                .attr('data-placement', 'top')
                .attr('data-html', 'true')
                .attr('title', `<b>${doc.title}</br>${doc.source}</b>`).tooltip({ delay: { show: 20 } });
            // Create Delete 'x' Button
            var deleteButton = $('<i></i>')
                .addClass('fa fa-times')
                .attr('aria-hidden', 'true')
                .attr('aria-label', 'Delete document'); // Accessibility feature


            var deleteDiv = $('<div></div>')
                .addClass('btn p-0 btn-sm btn-danger ml-1')
                .append(deleteButton);

            var downloadButton = $('<i></i>')
                .addClass('fa fa-download')
                .attr('aria-hidden', 'true')
                .attr('aria-label', 'Download document'); // Accessibility feature

            var downloadDiv = $('<div></div>')
                .addClass('btn p-0 btn-sm btn-primary ml-1')
                .append(downloadButton);

            // Attach download event to open in a new tab
            downloadDiv.click(function () {
                window.open(`/download_doc_from_conversation/${conversation_id}/${doc.doc_id}`, '_blank');
            });

            docButton.click(function () {
                if (ChatManager.shownDoc === doc.source) {
                    $("#chat-pdf-content").removeClass('d-none');
                } else {
                    showPDF(doc.source, "chat-pdf-content", "/proxy_shared");
                    $("#chat-pdf-content").removeClass('d-none');
                    if ($("#chat-content").length > 0) {
                        $("#chat-content").addClass('d-none');
                    }
                    // set shownDoc in ChatManager
                    ChatManager.shownDoc = doc.source;
                }

            });


            // Attach delete event
            deleteDiv.click(function (event) {
                event.stopPropagation(); // Prevents the click event from bubbling up to the docButton
                ChatManager.deleteDocument(conversation_id, $(this).parent().data('doc-id'))
                    .catch(function () {
                        alert("Error deleting the document.");
                    });
            });
            docButton.append(downloadDiv);
            docButton.append(deleteDiv);
            // Create a container for each pair of document and delete buttons
            var container = $('<div></div>')
                .addClass('d-inline-block')
                .append(docButton)


            // Append the container to the chat_doc_view
            chat_doc_view.append(container);
        });
    },
    deleteMessage: function (conversationId, messageId, index) {
        return $.ajax({
            url: '/delete_message_from_conversation/' + conversationId + '/' + messageId + '/' + index,
            type: 'DELETE',
            success: function (response) {
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
            error: function (response) {
                alert('Refresh page, delete error, Error: ' + response.responseText);
            }
        });
    },
    moveMessagesUpOrDown: function (messageIds, direction) {
        conversationId = ConversationManager.activeConversationId;
        return $.ajax({
            url: '/move_messages_up_or_down/' + conversationId,
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({
                message_ids: messageIds,
                direction: direction
            }),
            success: function (response) {
                console.log(response);
            },
            error: function (response) {
                alert('Refresh page, move messages error, Error: ' + response.responseText);
            }
        });
    },
    renderMessages: function (conversationId, messages, shouldClearChatView, initialize_voting = true, history_message_ids = [], skip_one = false) {
        if (shouldClearChatView) {
            $('#chatView').empty();  // Clear the chat view first
            cleanupMessageObservers();
        }
        
        // Timer for URL update
        let focusTimer = null;
        let currentFocusedMessageId = null;
        var messageElement = null;
        
        messages.forEach(function (message, index, array) {
            // $(document).find('.card') count number of card elements in the document
            card_elements_count = $(document).find('.card').length;
            index = card_elements_count;
            var senderText = message.sender === 'user' ? 'You' : 'Assistant';
            var showHide = message.show_hide || 'hide';
            messageElement = $('<div class="mb-1 mt-0 card w-100 my-1 d-flex flex-column message-card"></div>');
            // Create action dropdown for left side (doubts, delete, move)
            var actionDropdown = `
                <div class="dropdown d-inline-block">
                    <button class="btn btn-sm p-1 dropdown-toggle-no-caret" type="button" data-toggle="dropdown" aria-haspopup="true" aria-expanded="false" title="Message Actions">
                        <i class="bi bi-three-dots-vertical"></i>
                    </button>
                    <div class="dropdown-menu dropdown-menu-left">
                        <a class="dropdown-item show-doubts-button" href="#" message-index="${index}" message-id="${message.message_id}">
                            <i class="bi bi-question-circle mr-2"></i>Show Doubts
                        </a>
                        <a class="dropdown-item ask-doubt-button" href="#" message-index="${index}" message-id="${message.message_id}">
                            <i class="bi bi-plus-circle mr-2"></i>Ask New Doubt
                        </a>
                        <div class="dropdown-divider"></div>
                        <a class="dropdown-item move-message-up-button" href="#" message-index="${index}" message-id="${message.message_id}">
                            <i class="bi bi-arrow-up mr-2"></i>Move Up
                        </a>
                        <a class="dropdown-item move-message-down-button" href="#" message-index="${index}" message-id="${message.message_id}">
                            <i class="bi bi-arrow-down mr-2"></i>Move Down
                        </a>
                        <div class="dropdown-divider"></div>
                        <a class="dropdown-item delete-message-button text-danger" href="#" message-index="${index}" message-id="${message.message_id}">
                            <i class="bi bi-trash-fill mr-2"></i>Delete Message
                        </a>
                    </div>
                </div>`;
            
            var cardHeader = $(`<div class="card-header d-flex justify-content-between align-items-center" message-index="${index}" message-id=${message.message_id}>
                <div class="d-flex align-items-center">
                    <input type="checkbox" class="history-message-checkbox mr-2" id="message-checkbox-${message.message_id}" message-id=${message.message_id}>
                    <small><small><strong>` + senderText + `</strong></small></small>
                    ${actionDropdown}
                </div>
                <div class="d-flex align-items-center">
                    <button class="btn btn-sm p-1 copy-btn-header" title="Copy Text">
                        <i class="bi bi-clipboard"></i>
                    </button>
                    <div class="dropdown d-inline-block">
                        <button class="btn btn-sm p-1 dropdown-toggle-no-caret vote-menu-toggle" type="button" data-toggle="dropdown" aria-haspopup="true" aria-expanded="false" title="More Options">
                            <i class="bi bi-three-dots-vertical"></i>
                        </button>
                        <div class="dropdown-menu dropdown-menu-right vote-dropdown-menu">
                            <!-- Vote buttons will be inserted here by initialiseVoteBank -->
                        </div>
                    </div>
                </div>
            </div>`);
            var cardBody = $('<div class="card-body chat-card-body" style="font-size: 0.8rem;"></div>');
            var textElem = $('<div id="message-render-space" class="card-text actual-card-text"></div>');
            textElem.html(message.text.replace(/\n/g, '  \n'))

            cardBody.append(textElem);
            messageElement.append(cardHeader);
            messageElement.append(cardBody);

            // Depending on who the sender is, we adjust the alignment and add different background shading
            
            if (message.sender == 'user') {
                // messageElement.addClass('ml-md-auto');  // For right alignment
                messageElement.css('background-color', '#fdfdfd');  // Even lighter shade of purple
                if (message.text.trim().length > 0) {
                    msgElements = [$(messageElement)]
                    initialiseVoteBank(messageElement, message.text, contentId = message.message_id, activeDocId = ConversationManager.activeConversationId, disable_voting = true);
                    
                }
            } else {
                if (message.text.trim().length > 0) {
                    msgElements = [$(messageElement)]
                    initialiseVoteBank(messageElement, message.text, contentId = message.message_id, activeDocId = ConversationManager.activeConversationId, disable_voting = !initialize_voting);
                    
                }
                // messageElement.addClass('mr-md-auto');  // For left alignment
                messageElement.css('background-color', '#ffffff');  // Lighter shade of blue
            }
            
            if (message.text.trim().length > 0) {
                // Capture the current messageElement in a closure
                (function(currentMessageElement, currentMessage) {
                    renderInnerContentAsMarkdown(textElem, immediate_callback=function () {
                        const hasSlides = (
                            !!textElem.closest('.card-body').find('.slide-presentation-wrapper').length ||
                            !!textElem.closest('.card-body').find('.slide-external-link').length ||
                            (textElem && textElem.attr('data-has-slides') === 'true')
                        );
                        if (hasSlides) {
                            // Ensure historic messages with slides resize properly
                            setTimeout(function() {
                                var slideWrapper = textElem.closest('.card-body').find('.slide-presentation-wrapper');
                                if (slideWrapper.length > 0) {
                                    adjustCardHeightForSlides(slideWrapper);
                                }
                            }, 100);
                        } else if (textElem.text().length > 300) { // && (index < array.length - 2)
                            showMore(null, text = null, textElem = textElem, as_html = true, show_at_start = showHide === 'show', server_side = {
                                'message_id': currentMessage.message_id
                            }); // index >= array.length - 2
                        }
                        
                        // Add scroll-to-top button for old messages (assistant messages only)
                        // Now inside the callback with proper closure
                        if (currentMessage.sender !== 'user' && currentMessage.text.length > 300) {
                            // Check if button doesn't already exist to avoid duplicates
                            if (currentMessageElement.find('.scroll-to-top-btn').length === 0) {
                                if (typeof window.addScrollToTopButton === 'function') {
                                    window.addScrollToTopButton(currentMessageElement, '↑ Top of Answer', 'chat-scroll-top');
                                }
                            }
                        }
                    }, continuous = false, html = currentMessage.text.replace(/\n/g, '  \n'));
                })(messageElement, message);
            }

            var statusDiv = $('<div class="status-div d-flex align-items-center"></div>');
            var spinner = $('<div class="spinner-border text-primary" role="status"></div>');
            var statusText = $('<span class="status-text ml-2"></span>');
            var renderCloseToSource = $('#settings-render-close-to-source').is(':checked');

            statusDiv.append(spinner);
            statusDiv.append(statusText);
            messageElement.append(statusDiv);
            if (history_message_ids.length > 0 && renderCloseToSource) {
                // get all the "card message-card" and their message-id , then append the messageElement (new card) after the last card of the history_message_ids, if skip_one is true then skip one card further and then append the messageElement
                var cards = $('#chatView').find('.card.message-card');
                    var lastCard = null;
                    for (var i = 0; i < cards.length; i++) {
                        var card = cards[i];
                        var cardMessageId = $(card).find('.history-message-checkbox').attr('message-id');
                        if (history_message_ids.includes(cardMessageId)) {
                            lastCard = card;
                        }
                    }
                    if (lastCard) {
                        if (skip_one) {
                            $(lastCard).next().after(messageElement);
                        } else {
                            $(lastCard).after(messageElement);
                        }
                    } else {
                        $('#chatView').append(messageElement);
                    }
            }
            else {
                $('#chatView').append(messageElement);
            }
            // $('#chatView').append(messageElement);

            statusDiv.hide();
            statusDiv.find('.spinner-border').hide();
            
            // Add event handlers for immediate focus
            messageElement.on('click', function(e) {
                // Don't trigger on button clicks, checkboxes, or dropdown elements
                if ($(e.target).closest('.delete-message-button, .history-message-checkbox, .move-message-up-button, .move-message-down-button, .show-doubts-button, .ask-doubt-button, .copy-btn-header, .dropdown, .dropdown-menu, .dropdown-item, [data-toggle="dropdown"]').length > 0) {
                    return;
                }
                
                handleMessageFocus(message.message_id, conversationId);
            });
            
            // Add text selection event handler
            messageElement.on('selectstart mouseup', function(e) {
                // Don't trigger on button clicks, checkboxes, or dropdown elements
                if ($(e.target).closest('.delete-message-button, .history-message-checkbox, .move-message-up-button, .move-message-down-button, .show-doubts-button, .ask-doubt-button, .copy-btn-header, .dropdown, .dropdown-menu, .dropdown-item, [data-toggle="dropdown"]').length > 0) {
                    return;
                }
                
                // Check if text is actually selected
                setTimeout(function() {
                    const selection = window.getSelection();
                    if (selection && selection.toString().trim().length > 0) {
                        handleMessageFocus(message.message_id, conversationId);
                    }
                }, 10);
            });
            
            // Add focus event handler for keyboard navigation
            messageElement.on('focus focusin', function(e) {
                // Don't trigger on button clicks, checkboxes, or dropdown elements
                if ($(e.target).closest('.delete-message-button, .history-message-checkbox, .move-message-up-button, .move-message-down-button, .show-doubts-button, .ask-doubt-button, .copy-btn-header, .dropdown, .dropdown-menu, .dropdown-item, [data-toggle="dropdown"]').length > 0) {
                    return;
                }
                
                handleMessageFocus(message.message_id, conversationId);
            });
        });

        setTimeout(function() {
            mermaid.run({querySelector: "pre.mermaid"});
        }, 100);
        
        // Function to handle message focus and URL update
        function handleMessageFocus(messageId, convId) {
            // Clear existing timer if any
            if (focusTimer) {
                clearTimeout(focusTimer);
            }
            
            // Don't restart timer if same message is already focused
            messageIdInUrl = getMessageIdFromUrl();
            if (currentFocusedMessageId === messageId && messageIdInUrl === messageId) {
                return;
            }
            
            currentFocusedMessageId = messageId;
            
            // Set new timer for 5 seconds
            focusTimer = setTimeout(function() {
                updateUrlWithMessageId(convId, messageId);
                focusTimer = null;
            }, 1000);
        }
        
        
        $(".delete-message-button").off().on("click", function (event) {
            event.preventDefault();
            event.stopPropagation();
            var messageId = $(this).attr('message-id');
            var messageIndex = $(this).attr('message-index');
            $(this).closest('.card').remove();
            ChatManager.deleteMessage(conversationId, messageId, messageIndex);
        });
        $(".move-message-up-button").off().on("click", function (event) {
            event.preventDefault();
            event.stopPropagation();
            var messageId = $(this).attr('message-id');
            var messageIndex = $(this).attr('message-index');
            moveMessagesUpOrDownCallback("up", messageId, messageIndex);
        });
        $(".move-message-down-button").off().on("click", function (event) {
            event.preventDefault();
            event.stopPropagation();
            var messageId = $(this).attr('message-id');
            var messageIndex = $(this).attr('message-index');
            moveMessagesUpOrDownCallback("down", messageId, messageIndex);
        });
        
        $(".show-doubts-button").off().on("click", function (event) {
            event.preventDefault();
            event.stopPropagation();
            var messageId = $(this).attr('message-id');
            DoubtManager.showDoubtsOverview(conversationId, messageId);
        });
        
        $(".ask-doubt-button").off().on("click", function (event) {
            event.preventDefault();
            event.stopPropagation();
            var messageId = $(this).attr('message-id');
            DoubtManager.askNewDoubt(conversationId, messageId);
        });
        
        // Initialize Bootstrap 4.6 dropdowns
        setTimeout(function() {
            // Bootstrap 4.6 dropdowns are initialized automatically with data-toggle="dropdown"
            // Just ensure they work properly by triggering any needed setup
            $('[data-toggle="dropdown"]').dropdown();
        }, 50);
        // var chatView = $('#chatView');
        // chatView.scrollTop(chatView.prop('scrollHeight'));
        
        // Check if URL contains a message ID and scroll to that message
        const messageIdFromUrl = getMessageIdFromUrl();
        if (messageIdFromUrl && shouldClearChatView) {
            // Use setTimeout to ensure DOM is fully updated after rendering
            setTimeout(function() {
                const targetMessageElement = $(`[message-id="${messageIdFromUrl}"]`);
                const targetMessageCard = targetMessageElement.length > 0 ? targetMessageElement.closest('.card') : $();
                if (targetMessageCard && targetMessageCard.length > 0) {
                    // REMOVED: Auto-scroll to target message - was interrupting user reading
                    // targetMessageCard[0].scrollIntoView({
                    //     behavior: 'smooth',
                    //     block: 'center'
                    // });
                    
                    // Optional: Add a temporary highlight effect (keeping this for visual feedback)
                    targetMessageCard.addClass('highlight-message');
                    setTimeout(function() {
                        targetMessageCard.removeClass('highlight-message');
                    }, 2000);
                }
            }, 100);
        }
        
        // Call next question suggestions after rendering messages
        if (shouldClearChatView) {
            // Use setTimeout to ensure DOM is fully updated and messages are rendered
            setTimeout(function() {
                renderNextQuestionSuggestions(conversationId);
            }, 200);
        }
        
        return messageElement;
    },




    sendMessage: function (conversationId, messageText, checkboxes, links, search) {
        // Render user's message immediately
        var userMessage = {
            sender: 'user',
            text: messageText
        };
        history_message_ids = checkboxes['history_message_ids'] || []

        ChatManager.renderMessages(conversationId, [userMessage], false, true, history_message_ids, false);

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

function getConversationIdFromUrl(url) {  
    const path = url ? new URL(url).pathname : window.location.pathname;
    const pathParts = path.split('/');  
    // Remove any hash fragments from the end of the path
    const cleanPath = pathParts[pathParts.length - 1].split('#')[0];
    pathParts[pathParts.length - 1] = cleanPath;
    
      
    // Check if the URL contains a conversation ID  
    if (pathParts.length > 2 && pathParts[1] === 'interface') {  
        return pathParts[2];  
    }  
    return null;  
}  

function updateUrlWithConversationId(conversationId) {  
    // check if the conversation id is already in the url
    if (window.location.pathname.includes('interface/' + conversationId + '/')) {
        return;
    }

    // get message id from the url  
    var messageId = getMessageIdFromUrl();
    // Update the URL without reloading the page  
    if (messageId) {
        window.history.pushState({conversationId: conversationId, messageId: messageId}, '', '/interface/' + conversationId + '/' + messageId);  
    } else {
        window.history.pushState({conversationId: conversationId}, '', '/interface/' + conversationId);  
    }
} 

// Similar to above functions we also need a function to clear the url of the conversation id and just make it /interface/
function clearUrlofConversationId() {
    window.history.pushState({}, '', '/interface/');
}


function loadConversations(autoselect = true) {
    return WorkspaceManager.loadConversationsWithWorkspaces(autoselect);
}

function activateChatTab() {
    loadConversations();
    $('#review-assistant-view').hide();
    $('#references-view').hide();
    $('#pdf-view').hide();
    $('#chat-assistant-view').show();
    // REMOVED: Auto-scroll to bottom on chat tab activation - was interrupting user reading
    // var chatView = $('#chatView');
    // chatView.scrollTop(chatView.prop('scrollHeight'));
    $('#messageText').focus();
    $("#chat-pdf-content").addClass('d-none');
    $("#chat-content").removeClass('d-none');
    pdfTabIsActive();
    // toggleSidebar();
    var otherSidebar = $('#doc-keys-sidebar');
    var sidebar = $('#chat-assistant-sidebar');
    sidebar.addClass('d-none');
    otherSidebar.addClass('d-none');
    var contentCol = $('#content-col');
    contentCol.removeClass('col-md-10').addClass('col-md-12');
    var contentCol = $('#chat-assistant');
    contentCol.removeClass('col-md-10').addClass('col-md-12');
}

function moveMessagesUpOrDownCallback(direction, messageId=null, messageIndex=null) {
    var history_message_ids = []
    $(".history-message-checkbox").each(function () {
        var message_id = $(this).attr('message-id');
        var checked = $(this).prop('checked');
        if (checked) {
            history_message_ids.push(message_id);
            // remove the checked
            $(this).prop('checked', false);
        }
    });
    if (messageId) {
        history_message_ids.push(messageId);
    }
    if (history_message_ids.length === 0) {
        return;
    }
    if (history_message_ids.length > 0) {
        movePromise = ChatManager.moveMessagesUpOrDown(history_message_ids, direction);
        movePromise.done(function () {
            // Get all selected message cards
            var selectedCards = [];
            history_message_ids.forEach(function(messageId) {
                var card = $(`[message-id="${messageId}"]`).closest('.card');
                if (card.length) {
                    selectedCards.push(card);
                }
            });

            // Sort cards by their position in the DOM
            selectedCards.sort(function(a, b) {
                return $(a).index() - $(b).index(); 
            });

            if (direction === "up") {
                // Move cards up one position, starting from top
                selectedCards.forEach(function(card) {
                    var prev = $(card).prev('.card');
                    if (prev.length) {
                        prev.before(card);
                    }
                });
            } else if (direction === "down") {
                // Move cards down one position, starting from bottom
                $(selectedCards.reverse()).each(function(i, card) {
                    var next = $(card).next('.card');
                    if (next.length) {
                        next.after(card);
                    }
                });
            }
        });
        movePromise.fail(function () {
            alert('Error moving messages');
        });
    }
}


function sendMessageCallback() {
    // Remove any existing suggestions when sending a new message
    $('#chatView .next-question-suggestions').remove();
    
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
    var options = getOptions('chat-options', 'assistant');
    if (messageText.trim().length == 0 && (options['tell_me_more'] === false || options['tell_me_more'] === undefined)) {
        return;
    }
    // Lets split the messageText and get word count and then check if word count > 1000 then raise alert
    var wordCount = messageText.split(' ').length;
    $('#messageText').val('');  // Clear the messageText field
    $('#messageText').trigger('change');
    $('#messageText').prop('working', true);
    var links = $('#linkInput').length ? $('#linkInput').val().split('\n') : [];
    var search = $('#searchInput').length ? $('#searchInput').val().split('\n') : [];
    let parsed_message = parseMessageForCheckBoxes(messageText);

    var history_message_ids = []
    $(".history-message-checkbox").each(function () {
        var message_id = $(this).attr('message-id');
        var checked = $(this).prop('checked');
        if (checked) {
            history_message_ids.push(message_id);
            // remove the checked
            $(this).prop('checked', false);
        }
    });
    if (history_message_ids.length > 0) {
        parsed_message['history_message_ids'] = history_message_ids;
    }

    // messageText = parsed_message.text;
    options = mergeOptions(parsed_message, options)
    if (options['tell_me_more'] && messageText.trim().length == 0) {
        messageText = 'Tell me more';
    }

    if (options["search_exact"] && messageText.trim().length > 0) {
        messageText = messageText.replace("/search_exact", " ").trim();
        search = messageText.split('\n');
        options["perform_web_search"] = true
    }
    const booleanKeys = Object.keys(options).filter(key => typeof options[key] === 'boolean');
    const allFalse = booleanKeys.every(key => options[key] === false);
    if ((wordCount > 50000 && !allFalse) || (wordCount > 75000)) {
        alert('Please enter a message with less words');
        $('#messageText').prop('working', false);
        return;
    }

    ChatManager.sendMessage(ConversationManager.activeConversationId, messageText, options, links, search).then(function (response) {
        if (!response.ok) {
            alert('An error occurred: ' + response.status);
            // Reset UI state on error
            $('#stopResponseButton').hide();
            $('#sendMessageButton').show();
            $('#messageText').prop('working', false);
            return;
        }
        // $('#messageText').val('');  // Clear the messageText field
        history_message_ids = options['history_message_ids'] || []

        // Call the renderStreamingResponse function to handle the streaming response
        renderStreamingResponse(response, ConversationManager.activeConversationId, messageText, history_message_ids);
        $('#linkInput').val('')
        $('#searchInput').val('')
        if (!/Mobi|Android/i.test(navigator.userAgent) && !/iPhone/i.test(navigator.userAgent) && window.innerWidth > 768) {
            $('#messageText').focus();
        }
        ConversationManager.fetchMemoryPad().fail(function () {
            alert('Error fetching memory pad');
        });
        
        // Trigger PKB memory update proposal check (with delay to not interrupt streaming)
        // Only check if PKBManager is available
        if (typeof PKBManager !== 'undefined' && PKBManager.checkMemoryUpdates) {
            setTimeout(function() {
                // Get conversation summary if available
                var conversationSummary = '';
                try {
                    conversationSummary = ConversationManager.currentConversationSummary || '';
                } catch (e) {
                    conversationSummary = '';
                }
                
                PKBManager.checkMemoryUpdates(conversationSummary, messageText, '');
            }, 3000);  // 3 second delay to allow streaming to start
        }
    }).catch(function(error) {
        // Reset UI state on error
        $('#stopResponseButton').hide();
        $('#sendMessageButton').show();
        $('#messageText').prop('working', false);
        console.error('Error sending message:', error);
        alert('Error sending message: ' + error.message);
    });
    var chatView = $('#chatView');
    // chatView.scrollTop(chatView.prop('scrollHeight'));
}

function scrollToBottom() {
    var $chatView = $('#chatView');
    var $scrollToBottomBtn = $('#scrollToBottomBtn');
    var $messageText = $('#messageText');


    // Function to check the scroll position
    function checkScroll() {
        // Calculate the distance from the bottom
        var scrollTop = $chatView.scrollTop();
        var scrollHeight = $chatView.prop('scrollHeight');
        var chatViewHeight = $chatView.innerHeight();
        var distanceFromBottom = scrollHeight - (scrollTop + chatViewHeight);

        // Show button if more than 400 pixels from the bottom, otherwise hide and it is chat context
        chat_area = $("#chat-content")
        // if chat area is visible
        is_chat_visible = chat_area.is(':visible') && !chat_area.hasClass('d-none')

        if (distanceFromBottom > 100 && is_chat_visible) {
            // Set the bottom position to 80px (no longer dependent on toggle state)
            $scrollToBottomBtn.css('bottom', '80px');
            $scrollToBottomBtn.show();
        } else {
            $scrollToBottomBtn.hide();
        }
    }

    checkScroll();
    // Scroll event
    $chatView.on('scroll', function () {
        checkScroll();
    });

    $chatView.on('change', function () {
        checkScroll();
    });

    // check for any dom node change or insert or edit or inner html change in $chatView
    $chatView.on('DOMSubtreeModified', function () {
        checkScroll();
    });


    // Click event for the button
    $scrollToBottomBtn.click(function () {
        $chatView.animate({ scrollTop: $chatView.prop("scrollHeight") }, "fast");
    });

    // Initial check in case the page is loaded in a scrolled state
    checkScroll();
}

// Function to render next question suggestions as clickable pills
function renderNextQuestionSuggestions(conversationId, retryCount = 0) {
    // CONFIGURATION SWITCHES - Modify these as needed
    let LAYOUT_MODE = 'two_lines'; // Options: 'single_line', 'two_lines', 'one_per_line'
    const REDUCED_FONT_SIZE = true; // Set to true to use smaller fonts for better fit
    
    // Remove any existing suggestions first
    $('#chatView .next-question-suggestions').remove();
    
    // Don't retry more than 2 times (initial + 5s + 10s)
    if (retryCount > 2) {
        console.log('Max retries reached for next question suggestions');
        return;
    }
    
    // Initialize chat controls toggle handler
    initializeChatControlsToggleHandler();
    
    // Fetch suggestions from the API
    $.ajax({
        url: `/get_next_question_suggestions/${conversationId}`,
        method: 'GET',
        success: function(response) {
            const suggestions = response.suggestions || [];
            
            // If suggestions are empty and we haven't exceeded retry limit
            if (suggestions.length === 0 && retryCount < 3) {
                const retryDelay = retryCount === 0 ? 3000 : retryCount === 1 ? 7000 : 12000; // 3s then 7s then 12s
                console.log(`No suggestions found, retrying in ${retryDelay/1000}s (attempt ${retryCount + 1})`);
                setTimeout(() => {
                    renderNextQuestionSuggestions(conversationId, retryCount + 1);
                }, retryDelay);
                return;
            }
            
            // If still no suggestions after retries, don't show anything
            if (suggestions.length === 0) {
                return;
            }
            
            // Determine if mobile or desktop
            const isMobile = window.innerWidth <= 768; // Bootstrap's md breakpoint

            LAYOUT_MODE = isMobile ? 'two_lines' : LAYOUT_MODE;
            
            // Configure layout based on mode and device
            let containerClasses, maxSuggestions, pillsPerRow;
            
            switch (LAYOUT_MODE) {
                case 'single_line':
                    containerClasses = 'd-flex flex-nowrap overflow-auto gap-2';
                    maxSuggestions = isMobile ? 2 : 4;
                    pillsPerRow = maxSuggestions;
                    break;
                    
                case 'two_lines':
                    containerClasses = 'd-flex flex-wrap gap-2';
                    maxSuggestions = isMobile ? 2 : 4;
                    pillsPerRow = Math.ceil(maxSuggestions / 2);
                    break;
                    
                case 'one_per_line':
                    containerClasses = 'd-flex flex-column gap-2';
                    maxSuggestions = isMobile ? 3 : 4;
                    pillsPerRow = 1;
                    break;
                    
                default:
                    containerClasses = 'd-flex flex-wrap gap-2';
                    maxSuggestions = isMobile ? 2 : 4;
                    pillsPerRow = 2;
            }
            
            const displaySuggestions = suggestions.slice(0, maxSuggestions);
            
            // Create the suggestions container
            const suggestionsContainer = $(`
                <div class="next-question-suggestions mt-3 mb-3 px-2 w-100">
                    <div class="${containerClasses} w-100 justify-content-${LAYOUT_MODE === 'one_per_line' ? 'stretch' : 'start'}">
                        
                    </div>
                </div>
            `);
            
            const pillsContainer = suggestionsContainer.find('.d-flex').first();
            
            // Create pills for each suggestion
            displaySuggestions.forEach((suggestion, index) => {
                // Calculate sizing based on layout mode and device
                let maxWidth, pillStyle, maxChars;
                
                // Font size configuration
                const baseFontSize = REDUCED_FONT_SIZE ? (isMobile ? '0.65rem' : '0.7rem') : (isMobile ? '0.75rem' : '0.8rem');
                const padding = REDUCED_FONT_SIZE ? (isMobile ? '0.2rem 0.4rem' : '0.3rem 0.6rem') : (isMobile ? '0.25rem 0.5rem' : '0.4rem 0.8rem');
                
                switch (LAYOUT_MODE) {
                    case 'single_line':
                        maxWidth = isMobile ? '280px' : '400px';
                        maxChars = isMobile ? 120 : 180;
                        pillStyle = `
                            border-radius: 15px; 
                            max-width: ${maxWidth}; 
                            min-width: ${isMobile ? '100px' : '120px'};
                            white-space: nowrap; 
                            overflow: hidden; 
                            text-overflow: ellipsis; 
                            font-size: ${baseFontSize};
                            padding: ${padding};
                            flex-shrink: 0;
                        `;
                        break;
                        
                    case 'two_lines':
                        maxWidth = isMobile ? '100%' : '48%';
                        maxChars = isMobile ? 160 : 180;
                        pillStyle = `
                            border-radius: 15px; 
                            width: ${maxWidth}; 
                            white-space: nowrap; 
                            overflow: hidden; 
                            text-overflow: ellipsis; 
                            font-size: ${baseFontSize};
                            padding: ${padding};
                            text-align: center;
                        `;
                        break;
                        
                    case 'one_per_line':
                        maxWidth = '100%';
                        maxChars = isMobile ? 160 : 180;
                        pillStyle = `
                            border-radius: 15px; 
                            width: ${maxWidth}; 
                            white-space: nowrap; 
                            overflow: hidden; 
                            text-overflow: ellipsis; 
                            font-size: ${baseFontSize};
                            padding: ${padding};
                            text-align: left;
                        `;
                        break;
                        
                    default:
                        maxWidth = isMobile ? '45%' : '350px';
                        maxChars = isMobile ? 25 : 40;
                        pillStyle = `
                            border-radius: 15px; 
                            max-width: ${maxWidth}; 
                            font-size: ${baseFontSize};
                            padding: ${padding};
                        `;
                }
                
                const displayText = suggestion.length > maxChars ? suggestion.substring(0, maxChars) + '...' : suggestion;
                
                const pill = $('<button>')
                    .addClass('btn btn-outline-primary btn-sm suggestion-pill')
                    .attr('style', pillStyle)
                    .attr('title', suggestion)
                    .attr('data-suggestion', suggestion)  // jQuery handles escaping automatically
                    .text(displayText);
                
                // Add click handler to fill messageText and send
                pill.on('click', function(e) {
                    e.preventDefault();
                    const fullSuggestion = $(this).data('suggestion');
                    
                    // Fill the message text area
                    $('#messageText').val(fullSuggestion);
                    
                    // Focus on the text area
                    $('#messageText').focus();
                    
                    // Trigger the send message function
                    sendMessageCallback();
                    
                    // Remove suggestions after sending
                    $('#chatView .next-question-suggestions').remove();
                });
                
                pillsContainer.append(pill);
            });
            
            // Append to chatView
            $('#chatView').append(suggestionsContainer);
            
            // Ensure suggestions are visible after adding them
            ensureSuggestionsVisible();
            
            // Add custom CSS for the different layout modes
            if (!$('#suggestion-pills-styles').length) {
                $('head').append(`
                    <style id="suggestion-pills-styles">
                        .next-question-suggestions {
                            position: relative;
                            z-index: 10;
                            background-color: white;
                            border-radius: 8px;
                            box-shadow: 0 -2px 4px rgba(0,0,0,0.05);
                            width: 100%;
                        }
                        .suggestion-pill {
                            transition: all 0.2s ease;
                            margin: 1px;
                            border: 1px solid #007bff;
                            background-color: #fff;
                            color: #007bff;
                        }
                        .suggestion-pill:hover {
                            transform: translateY(-1px);
                            box-shadow: 0 2px 6px rgba(0,123,255,0.25);
                            background-color: #007bff;
                            color: white;
                        }
                        .suggestion-pill:active {
                            transform: translateY(0);
                        }
                        
                        /* Single line mode - horizontal scroll if needed */
                        .next-question-suggestions .flex-nowrap {
                            scrollbar-width: thin;
                            scrollbar-color: #007bff transparent;
                        }
                        .next-question-suggestions .flex-nowrap::-webkit-scrollbar {
                            height: 4px;
                        }
                        .next-question-suggestions .flex-nowrap::-webkit-scrollbar-track {
                            background: transparent;
                        }
                        .next-question-suggestions .flex-nowrap::-webkit-scrollbar-thumb {
                            background-color: #007bff;
                            border-radius: 2px;
                        }
                        
                        /* Responsive adjustments */
                        @media (max-width: 768px) {
                            .next-question-suggestions {
                                margin-left: -4px;
                                margin-right: -4px;
                                padding-left: 4px;
                                padding-right: 4px;
                            }
                        }
                        
                        @media (min-width: 769px) {
                            .next-question-suggestions {
                                margin-left: -8px;
                                margin-right: -8px;
                            }
                        }
                    </style>
                `);
            }
        },
        error: function(xhr, status, error) {
            console.error('Failed to fetch next question suggestions:', error);
            
            // Retry on error if we haven't exceeded retry limit
            if (retryCount < 3) {
                const retryDelay = retryCount === 0 ? 3000 : retryCount === 1 ? 7000 : 12000; // 3s then 7s then 12s
                setTimeout(() => {
                    renderNextQuestionSuggestions(conversationId, retryCount + 1);
                }, retryDelay);
            }
        }
    });
}

// REMOVED: Function to ensure suggestions remain visible when layout changes
// This was causing unwanted auto-scrolling that interrupted user reading
function ensureSuggestionsVisible() {
    // DISABLED: Auto-scroll to show suggestions - was interrupting user reading
    // const suggestionsElement = $('#chatView .next-question-suggestions');
    // if (suggestionsElement.length > 0) {
    //     // Small delay to ensure DOM is updated
    //     setTimeout(function() {
    //         // Scroll chatView to show the suggestions
    //         const chatView = $('#chatView');
    //         const suggestionsOffset = suggestionsElement.offset();
    //         const chatViewOffset = chatView.offset();
    //         const chatViewHeight = chatView.height();
    //         const suggestionsHeight = suggestionsElement.outerHeight();
    //         
    //         // Check if suggestions are visible within the chatView bounds
    //         if (suggestionsOffset && chatViewOffset) {
    //             const relativeTop = suggestionsOffset.top - chatViewOffset.top;
    //             const isVisible = relativeTop >= 0 && (relativeTop + suggestionsHeight) <= chatViewHeight;
    //             
    //             if (!isVisible) {
    //                 // Scroll to make suggestions visible with smooth animation
    //                 const newScrollTop = chatView.scrollTop() + relativeTop - (chatViewHeight - suggestionsHeight - 20);
    //                 chatView.animate({
    //                     scrollTop: newScrollTop
    //                 }, 300, 'swing');
    //             }
    //         }
    //     }, 100);
    // }
}

// Initialize chat controls toggle handler (call this once when page loads)
function initializeChatControlsToggleHandler() {
    // Only bind if not already bound - updated for settings modal
    if (!$('#chatSettingsButton').data('suggestions-handler-bound')) {
        $('#chatSettingsButton').on('click', function() {
            // Small delay to allow modal to open
            setTimeout(function() {
                ensureSuggestionsVisible();
            }, 150);
        });
        
        // Also handle toggleChatDocsView
        $('#toggleChatDocsView').on('click', function() {
            setTimeout(function() {
                ensureSuggestionsVisible();
            }, 150);
        });
        
        $('#chatSettingsButton').data('suggestions-handler-bound', true);
    }
    
    // Also handle window resize events
    if (!$(window).data('suggestions-resize-handler-bound')) {
        $(window).on('resize', function() {
            // Debounce resize events
            clearTimeout(window.suggestionsResizeTimeout);
            window.suggestionsResizeTimeout = setTimeout(function() {
                ensureSuggestionsVisible();
            }, 100);
        });
        $(window).data('suggestions-resize-handler-bound', true);
    }
}


