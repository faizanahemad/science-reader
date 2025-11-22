window.katex = katex;
var currentDomain = {
    domain: 'assistant', // finchat, search
    page_loaded: false,
    manual_domain_change: false,
}

var allDomains = ['finchat', 'search', 'assistant'];

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
        'ndjson': 'application/x-ndjson',
        'mp3': 'audio/mpeg',
        'mpeg': 'audio/mpeg',
        'wav': 'audio/wav',
        'wave': 'audio/wav',
        'm4a': 'audio/mp4',
        'aac': 'audio/aac',
        'flac': 'audio/flac',
        'xflac': 'audio/x-flac',
        'ogg': 'audio/ogg',
        'oga': 'audio/ogg',
        'opus': 'audio/opus',
        'webm': 'audio/webm',
        'wma': 'audio/x-ms-wma',
        'aiff': 'audio/aiff',
        'aif': 'audio/aiff',
        'aifc': 'audio/aiff',
        'mp4': 'video/mp4'
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
    // Auto-scroll textarea to bottom when adding newline at end
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
    var lineHeight;
    try {
        lineHeight = parseFloat(getComputedStyle(messageText[0]).lineHeight);
    } catch (e) {
        // Default to 20px line height if computation fails
        lineHeight = 20;
        console.log("Could not compute line height, using default value of 20px");
    }

    // Set max-height for 10 lines
    if (!height) {
        height = 10;
    }
    var maxHeight = lineHeight * height;
    messageText.css('max-height', maxHeight + 'px');

    // Set overflow to auto to ensure scrollbars appear if needed
    messageText.css('overflow-y', 'auto');
}

function showMore(parentElem, text = null, textElem = null, as_html = false, show_at_start = false, server_side = null) {

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

        // FIXED: Preserve scroll position when rebuilding content
        var $chatView = $('#chatView');
        

        var moreText = $('<span class="more-text" style="display:none;"></span>')
        moreText.html(text)
        moreText.find('.show-more').each(function () { $(this).remove(); })
        shortText = moreText.text().slice(0, 10);
        var lessText = $(`<span class="less-text" style="display:block;">${shortText}</span>`)
        previous_sm = textElem.find('.show-more').length
        var smClick = $(' <a href="#" class="show-more">[show]</a> ')
        var originalScrollTop = $chatView.scrollTop();
        textElem.empty()
        textElem.append(lessText)
        textElem.append(smClick)

        textElem.append(moreText)

        moreText.append(smClick.clone())

        // Restore scroll position after rebuilding content
        // $chatView.scrollTop(originalScrollTop);

        // FIXED: Restore scroll position after DOM changes
        requestAnimationFrame(function() {
            $chatView.scrollTop(originalScrollTop);
        });
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

    function toggle(event, api_call_trigger = true) {
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

        // if server_side is an object then call the server side flask api and save the state of whether we should show or hide the text
        if (server_side && typeof server_side === 'object' && api_call_trigger) {
            var show_hide = moreText.is(':visible') ? 'show' : 'hide';
            var message_id = server_side.message_id;
            var conversation_id = ConversationManager.activeConversationId;
            
            // Make API call to save show/hide state
            apiCall(`/show_hide_message_from_conversation/${conversation_id}/${message_id}/0`, 'POST', {
                'show_hide': show_hide
            }).done(function(data) {
                console.log('Show/hide state saved: ' + show_hide);
            }).fail(function(xhr, status, error) {
                alert('Failed to save show/hide state: ' + (xhr.responseJSON?.message || error || 'Unknown error'));
            });
        }
    }

    if (show_at_start) {
        toggle(null, false);
    }


    textElem.find('.show-more').click(toggle);
    return toggle;
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
    let copyBtn = $('<button>')
        .addClass('vote-btn')
        .addClass('copy-btn')
        .text('📋');
    let editBtn = $('<button>')
        .addClass('vote-btn')
        .addClass('edit-btn')
        .text('✏️');
    
    copyBtn.click(function () {
        copyToClipboard(cardElem, text.replace('<answer>', '').replace('</answer>', '').trim());
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

    // TTS button
    // ... existing code ...
    let ttsBtn = $('<button>')
        .addClass('vote-btn')
        .addClass('tts-btn')
        .html('<span style="font-size:1rem;">🔊 S</span>')  // Larger icon
        .css({
            'border-radius': '6px',
            'border': '1px solid',
            'margin-right': '3px',
            'padding': '2px 5px',
            'font-size': '0.85rem',
            'display': 'flex',
            'align-items': 'center',
            'justify-content': 'center'
        });

    let shortTtsBtn = $('<button>')
        .addClass('vote-btn')
        .addClass('short-tts-btn')
        .html('<span style="font-size:0.7rem;">S</span><span style="font-size:0.75rem;margin-left:2px;">🔉 SS</span>')  // Smaller text and icon
        .css({
            'border-radius': '6px',
            'border': '1px solid',
            'margin-right': '3px',
            'padding': '1px 4px',  // Even smaller padding
            'font-size': '0.7rem',
            'display': 'flex',
            'align-items': 'center',
            'justify-content': 'center'
        });

    let podcastTtsBtn = $('<button>')
        .addClass('vote-btn')
        .addClass('podcast-tts-btn')
        .html('<span style="font-size:0.8rem;">P</span><span style="font-size:0.9rem;margin-left:2px;">🔉 P</span>')
        .css({
            'border-radius': '6px',
            'border': '1px solid',
            'margin-right': '3px',
            'padding': '2px 4px',
            'font-size': '0.8rem',
            'display': 'flex',
            'align-items': 'center',
            'justify-content': 'center'
        });

    let shortPodcastTtsBtn = $('<button>')
        .addClass('vote-btn')
        .addClass('short-podcast-tts-btn')
        .html('<span style="font-size:0.7rem;">SP</span><span style="font-size:0.75rem;margin-left:2px;">🔉 SP</span>')  // Smaller text and icon
        .css({
            'border-radius': '6px',
            'border': '1px solid',
            'margin-right': '3px',
            'padding': '1px 4px',  // Even smaller padding
            'font-size': '0.7rem',
            'display': 'flex',
            'align-items': 'center',
            'justify-content': 'center'
        });
// ... existing code ...

    // We'll create a container for the audio or player
    function createAudioPlayer(audioUrl, autoPlay) {
        let audioContainer = $('<div>')
            .addClass('audio-container')
            .css({
                'display': 'flex',
                'align-items': 'center',
                'gap': '5px'
            });
        
        // If using streaming (autoPlay = true), the audioUrl is a MediaSource object URL
        // If not streaming, audioUrl is a full MP3 blob object URL

        let audioPlayer = $('<audio controls>')
            .addClass('tts-audio')
            .css({
                'height': '30px',
                'width': Math.min(window.innerWidth * 0.4, 400) + 'px'
            })
            .attr('src', audioUrl);

        // Autoplay if requested (HTML property)
        if (autoPlay) {
            audioPlayer.attr('autoplay', 'autoplay');
        }
        
        // Instead of an explicit "Loading..." item, you can add your own
        let loadingIndicator = $('<span>')
            .addClass('loading-indicator')
            .text('Loading...')
            .hide();

        // Refresh button
        let refreshBtn = $('<button>')
            .addClass('vote-btn')
            .addClass('refresh-tts-btn')
            .html('<i class="fas fa-sync-alt"></i>')
            .hide();
            
        // Close button to restore dropdown
        let closeBtn = $('<button>')
            .addClass('vote-btn')
            .addClass('close-tts-btn')
            .html('<i class="fas fa-times"></i>')
            .css({
                'margin-left': '5px',
                'color': '#dc3545'
            })
            .attr('title', 'Close Audio Player');

        // Refresh logic
        refreshBtn.click(() => {
            refreshBtn.hide();
            loadingIndicator.show();
            // Force recompute
            ConversationManager.convertToTTS(text, messageId, messageIndex, cardElem, true, autoPlay, shortTTS, podcastTTS)
                .then(newUrl => {
                    // Revoke old URL if needed
                    if (audioPlayer.attr('src')) {
                        URL.revokeObjectURL(audioPlayer.attr('src'));
                    }
                    audioPlayer.attr('src', newUrl);
                    loadingIndicator.hide();
                    refreshBtn.show();

                    if (autoPlay) {
                        audioPlayer[0].play().catch(e => console.log('Autoplay prevented:', e));
                    }
                })
                .catch(err => {
                    alert('Failed to refresh TTS: ' + err.message);
                    console.error(err);
                    loadingIndicator.hide();
                });
        });

        // Show refresh once the audio starts playing
        audioPlayer.on('play', () => {
            refreshBtn.show();
            loadingIndicator.hide();
        });

        // Close button logic
        closeBtn.click(() => {
            // Remove audio player container and restore dropdown
            let audioPlayerContainer = audioContainer.closest('.audio-player-container');
            let voteDropdown = audioPlayerContainer.prev('.dropdown');
            
            if (voteDropdown.length > 0) {
                voteDropdown.show();
                audioPlayerContainer.remove();
            } else {
                // Fallback: just remove the audio container
                audioContainer.remove();
            }
            
            // Revoke URL to free memory
            if (audioPlayer.attr('src')) {
                URL.revokeObjectURL(audioPlayer.attr('src'));
            }
        });

        audioContainer.append(loadingIndicator, audioPlayer, refreshBtn, closeBtn);
        return audioContainer;
    }

    // TTS click

    function handleTTSBtnClick(isShort, isPodcast = false) {
        const messageId = cardElem.find('.card-header').last().attr('message-id');
        const messageIndex = cardElem.find('.card-header').last().attr('message-index');
        
        // For demonstration: set autoPlay = true
        // If you want to decide this conditionally, you can do so based on user settings
        let autoPlay = true;  // We'll do streaming auto-play
        
        let audioContainer = createAudioPlayer('', autoPlay);
        

        // Find the vote dropdown and hide it, then show audio container
        let voteDropdown = cardElem.find('.vote-dropdown-menu').closest('.dropdown');
        let audioPlayerContainer = $('<div class="audio-player-container d-inline-block"></div>');
        audioPlayerContainer.append(audioContainer);
        
        if (voteDropdown.length > 0) {
            // Hide the dropdown and show audio player
            voteDropdown.hide();
            voteDropdown.after(audioPlayerContainer);
        } else {
            // Fallback for old button structure
            if (isPodcast) {
                if (isShort) {
                    ttsBtn.hide();
                    shortTtsBtn.hide();
                    podcastTtsBtn.hide();
                    shortPodcastTtsBtn.replaceWith(audioContainer);
                } else {
                    ttsBtn.hide();
                    shortTtsBtn.hide();
                    shortPodcastTtsBtn.hide();
                    podcastTtsBtn.replaceWith(audioContainer);
                }
            } else {
                if (isShort) {
                    ttsBtn.hide();
                    podcastTtsBtn.hide();
                    shortPodcastTtsBtn.hide();
                    shortTtsBtn.replaceWith(audioContainer);
                } else {
                    shortTtsBtn.hide();
                    podcastTtsBtn.hide();
                    shortPodcastTtsBtn.hide();
                    ttsBtn.replaceWith(audioContainer);
                }
            }
        }

        let loadingIndicator = audioContainer.find('.loading-indicator');
        let audioPlayer = audioContainer.find('audio');
        let refreshBtn = audioContainer.find('.refresh-tts-btn');

        loadingIndicator.show();
        audioPlayer.hide();
        

        shortTTS = isShort;
        podcastTTS = isPodcast;

        ConversationManager.convertToTTS(text, messageId, messageIndex, cardElem, false, autoPlay, shortTTS, podcastTTS)
            .then(audioUrl => {
                audioPlayer.attr('src', audioUrl);
                audioPlayer.show();
                loadingIndicator.hide();

                // Attempt immediate playback if autoPlay is set
                if (autoPlay) {
                    audioPlayer[0].play().catch(e => console.log('Autoplay prevented:', e));
                }
            })
            .catch(err => {
                loadingIndicator.text('Error generating audio');
                console.error('TTS Error:', err);
            });
    }
    ttsBtn.click(function() {
        handleTTSBtnClick(false);  // normal TTS
    });

    shortTtsBtn.click(function() {
        handleTTSBtnClick(true);   // short TTS
    });

    podcastTtsBtn.click(function() {
        handleTTSBtnClick(false, true);  // podcast TTS
    });

    shortPodcastTtsBtn.click(function() {
        handleTTSBtnClick(true, true);   // short podcast TTS
    });


    // Handle copy button in header
    let headerCopyBtn = cardElem.find('.copy-btn-header');
    if (headerCopyBtn.length > 0) {
        headerCopyBtn.click(function(e) {
            e.preventDefault();
            e.stopPropagation();
            copyBtn.click();
        });
    }
    
    // Find the dropdown menu in the card header
    let voteDropdown = cardElem.find('.vote-dropdown-menu');
    
    if (voteDropdown.length > 0) {
        // Clear existing content
        voteDropdown.empty();
        
        // Add TTS buttons as dropdown items
        let shortTtsItem = $('<a class="dropdown-item" href="#"><i class="bi bi-volume-up mr-2"></i>Short TTS</a>');
        let ttsItem = $('<a class="dropdown-item" href="#"><i class="bi bi-music-note mr-2"></i>Full TTS</a>');
        let shortPodcastItem = $('<a class="dropdown-item" href="#"><i class="bi bi-broadcast mr-2"></i>Short Podcast</a>');
        let podcastItem = $('<a class="dropdown-item" href="#"><i class="bi bi-broadcast-pin mr-2"></i>Full Podcast</a>');
        let editItem = $('<a class="dropdown-item" href="#"><i class="bi bi-pencil mr-2"></i>Edit Message</a>');
        
        // Add click handlers
        shortTtsItem.click(function(e) {
            e.preventDefault();
            handleTTSBtnClick(true);
        });
        
        ttsItem.click(function(e) {
            e.preventDefault();
            handleTTSBtnClick(false);
        });
        
        shortPodcastItem.click(function(e) {
            e.preventDefault();
            handleTTSBtnClick(true, true);
        });
        
        podcastItem.click(function(e) {
            e.preventDefault();
            handleTTSBtnClick(false, true);
        });
        
        editItem.click(function(e) {
            e.preventDefault();
            editBtn.click();
        });
        
        // Add items to dropdown
        voteDropdown.append(shortTtsItem, ttsItem);
        
        // Add podcast items for wider screens
        if (window.innerWidth > 768) {
            voteDropdown.append(shortPodcastItem, podcastItem);
        }
        
        voteDropdown.append($('<div class="dropdown-divider"></div>'), editItem);
        
    } else {
        // Fallback to old vote box if dropdown not found
        let voteBox = $('<div>')
            .addClass('vote-box')
            .css({
                'position': 'absolute',
                'top': '5px',
                'right': '30px'
            });

        let isWideScreen = window.innerWidth > 768;
        if (isWideScreen) {
            voteBox.append(shortTtsBtn, ttsBtn, shortPodcastTtsBtn, podcastTtsBtn, editBtn, copyBtn);
        } else {
            voteBox.append(shortTtsBtn, ttsBtn, editBtn, copyBtn);
        }
        cardElem.find('.vote-box').remove();
        cardElem.append(voteBox);
    }

    return;
}

/**
 * Add a scroll-to-top button to a card element
 * @param {jQuery} cardElem - The card element to add the button to
 * @param {string} buttonText - Text for the button (default: "↑ Top")
 * @param {string} buttonClass - Additional CSS classes for the button
 */
window.addScrollToTopButton = function(cardElem, buttonText = '↑ Top', buttonClass = '') {
    console.log('[addScrollToTopButton] Called with:', {
        cardElem: cardElem,
        cardExists: cardElem && cardElem.length > 0,
        buttonText: buttonText,
        buttonClass: buttonClass
    });
    
    // Check if button already exists to avoid duplicates
    if (cardElem.find('.scroll-to-top-btn').length > 0) {
        console.log('[addScrollToTopButton] Button already exists, skipping');
        return; // Button already exists, don't add another
    }
    
    console.log('[addScrollToTopButton] Creating button...');
    // Create the scroll-to-top button
    let scrollTopBtn = $('<button>')
        .addClass('btn btn-sm scroll-to-top-btn ' + buttonClass)
        .html(buttonText)
        .css({
            'position': 'absolute',
            'bottom': '5px',
            'right': '5px',
            'padding': '2px 8px',
            'font-size': '0.75rem',
            'background-color': '#f8f9fa',
            'border': '1px solid #dee2e6',
            'border-radius': '4px',
            'opacity': '0.8',
            'z-index': '10',
            'transition': 'opacity 0.2s'
        })
        .hover(
            function() { $(this).css('opacity', '1'); },
            function() { $(this).css('opacity', '0.8'); }
        );
    
    // Click handler to scroll to top of the card
    scrollTopBtn.click(function(e) {
        e.preventDefault();
        e.stopPropagation();
        
        // Check if card is in doubt chat messages (modal)
        const doubtMessages = $('#doubt-chat-messages');
        if (doubtMessages.length > 0 && doubtMessages.find(cardElem).length > 0) {
            // Card is inside doubt modal
            const cardRelativeTop = cardElem.position().top;
            
            // Scroll doubt messages container to show the top of the card
            doubtMessages.animate({
                scrollTop: doubtMessages.scrollTop() + cardRelativeTop
            }, 300, 'swing');
            return;
        }
        
        // Check if card is in chat view
        const chatView = $('#chatView');
        if (chatView.length > 0 && chatView.find(cardElem).length > 0) {
            // Card is inside chatView
            const cardRelativeTop = cardElem.position().top;
            
            // Scroll chatView to show the top of the card
            chatView.animate({
                scrollTop: chatView.scrollTop() + cardRelativeTop
            }, 300, 'swing');
            return;
        }
        
        // Check if card is in any modal body
        const modalBody = cardElem.closest('.modal-body');
        if (modalBody.length > 0) {
            // Card is in a modal
            const cardRelativeTop = cardElem.position().top;
            
            // Scroll modal body to show the top of the card
            modalBody.animate({
                scrollTop: modalBody.scrollTop() + cardRelativeTop
            }, 300, 'swing');
            return;
        }
        
        // Default: Card is in the main window, scroll window
        const cardTop = cardElem.offset().top;
        $('html, body').animate({
            scrollTop: cardTop - 20 // 20px padding from top
        }, 300, 'swing');
    });
    
    // Ensure the card has relative positioning for absolute button positioning
    const currentPosition = cardElem.css('position');
    console.log('[addScrollToTopButton] Card current position:', currentPosition);
    if (currentPosition === 'static') {
        console.log('[addScrollToTopButton] Setting position to relative');
        cardElem.css('position', 'relative');
    }
    
    // Add the button to the card
    console.log('[addScrollToTopButton] Appending button to card...');
    cardElem.append(scrollTopBtn);
    
    // Verify button was added
    const buttonAdded = cardElem.find('.scroll-to-top-btn').length > 0;
    console.log('[addScrollToTopButton] Button added successfully:', buttonAdded);
    
    if (!buttonAdded) {
        console.error('[addScrollToTopButton] Failed to add button!');
        console.log('[addScrollToTopButton] Card still exists:', cardElem.length > 0);
        console.log('[addScrollToTopButton] Card parent:', cardElem.parent().length > 0);
        console.log('[addScrollToTopButton] Card is attached to DOM:', $.contains(document, cardElem[0]));
    }
    
    // Return the button element in case further customization is needed
    return scrollTopBtn;
}

const markdownParser = new marked.Renderer();

// Create a marked extension for math
const mathExtension = {
    name: 'math',
    level: 'block',
    start(src) { return src.match(/^\$\$/)?.index; },
    tokenizer(src, tokens) {
        const rule = /^\$\$([\s\S]*?)\$\$/;
        const match = rule.exec(src);
        if (match) {
            return {
                type: 'math',
                raw: match[0],
                text: match[1].trim()
            };
        }
    },
    renderer(token) {
        return `$$${token.text}$$`;
    }
};

// Configure marked with the math extension
marked.use({ extensions: [mathExtension] });

marked.setOptions({
    renderer: markdownParser,
    pedantic: false,
    gfm: true,
    breaks: false,
    sanitize: false,
    smartLists: true,
    smartypants: false,
    xhtml: true
});
markdownParser.text = function(text) {
    // Preserve math delimiters from being processed
    // This prevents marked from interfering with $ signs
    return text;
};

const options = {
    throwOnError: false
  };
  
marked.use(markedKatex(options));

/**
 * Build a standalone HTML document string that renders the given slides HTML
 * inside a Reveal.js deck.
 * The provided slidesHtml must include <section> elements only.
 */
function buildStandaloneSlidesPage(slidesHtml) {
    return `<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Slides</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/reveal.js@4.3.1/dist/reveal.css">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/reveal.js@4.3.1/dist/theme/white.css">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/reveal.js@4.3.1/plugin/highlight/monokai.css">
    <style>
        body, html { margin: 0; padding: 0; height: 100%; }
        .reveal { height: 100%; background: #fff; }
        .reveal .slides section { text-align: left; }
    </style>
</head>
<body>
    <div class="reveal">
        <div class="slides">
            ${slidesHtml}
        </div>
    </div>
    <script src="https://cdn.jsdelivr.net/npm/reveal.js@4.3.1/dist/reveal.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/reveal.js@4.3.1/plugin/notes/notes.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/reveal.js@4.3.1/plugin/highlight/highlight.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/reveal.js@4.3.1/plugin/math/math.js"></script>
    <script>
        (function() {
            const deck = new Reveal(document.querySelector('.reveal'), {
                embedded: false,
                // IMPORTANT: Disable hash/history for blob/about pages to avoid SecurityError
                hash: false,
                controls: true,
                progress: true,
                center: false,
                transition: 'slide',
                backgroundTransition: 'fade',
                plugins: [RevealHighlight, RevealMath.KaTeX]
            });
            try { deck.initialize(); } catch (e) { console.error('Reveal init error:', e); }
        })();
    </script>
  </body>
</html>`;
}

/**
 * Detect if provided HTML is a full HTML document (has <!DOCTYPE html> or <html> root)
 */
function isFullHtmlDocument(htmlString) {
    if (!htmlString || typeof htmlString !== 'string') return false;
    var s = htmlString.trim();
    return (/^<!DOCTYPE\s+html/i.test(s) || /^<html[\s>]/i.test(s));
}

/**
 * If given embedded Reveal markup, extract only the direct <section>…</section> nodes
 * contained inside the first <div class="slides">…</div>. If not found, returns input.
 */
function extractSectionsFromReveal(htmlString) {
    if (!htmlString || typeof htmlString !== 'string') return htmlString;
    var match = htmlString.match(/<div[^>]*class=["']?slides["']?[^>]*>([\s\S]*?)<\/div>/i);
    if (match && match[1]) {
        return match[1].trim();
    }
    return htmlString;
}

/**
 * Split content into an ordered list of parts around <slide-presentation>…</slide-presentation> blocks.
 * Returns { parts: Array<{type: 'text'|'slide', content: string}>, incomplete: boolean }
 * If a closing tag is missing (streaming), 'incomplete' is true and only text before the
 * opening tag will be returned in parts.
 */
function splitSlidePresentationParts(htmlString) {
    var parts = [];
    var i = 0;
    var startTag = '<slide-presentation>';
    var endTag = '</slide-presentation>';
    while (i < htmlString.length) {
        var startIdx = htmlString.indexOf(startTag, i);
        if (startIdx === -1) {
            // remaining text
            parts.push({ type: 'text', content: htmlString.slice(i) });
            break;
        }
        // text before slide
        if (startIdx > i) {
            parts.push({ type: 'text', content: htmlString.slice(i, startIdx) });
        }
        var endIdx = htmlString.indexOf(endTag, startIdx + startTag.length);
        if (endIdx === -1) {
            // Incomplete slide block (streaming). Stop here; don't include partial slide
            return { parts: parts, incomplete: true };
        }
        // Extract inner slide content
        var inner = htmlString.slice(startIdx + startTag.length, endIdx);
        parts.push({ type: 'slide', content: inner });
        i = endIdx + endTag.length;
    }
    return { parts: parts, incomplete: false };
}

/**
 * Create a blob URL for the provided HTML string so it can be opened in a new window.
 */
function createSlidesBlobUrl(htmlString) {
    try {
        const blob = new Blob([htmlString], { type: 'text/html;charset=utf-8' });
        return URL.createObjectURL(blob);
    } catch (e) {
        console.error('Failed to create slides blob URL', e);
        return 'about:blank';
    }
}

markdownParser.codespan = function (text) {
    return '<code class="inline-code">' + text + '</code>';
};
markdownParser.code = function (code, language) {
    const validLanguage = hljs.getLanguage(language) ? language : 'plaintext';
    if (validLanguage === 'plaintext') {
        var highlighted = hljs.highlightAuto(code).value;
    } else {
        var highlighted = hljs.highlight(validLanguage, code).value;
    }
    number_of_lines = code.split('\n').length;
    show_by_default = number_of_lines < 8 || (language === 'markdown' && number_of_lines < 15) || (language === 'md' && number_of_lines < 15) || (language === 'plaintext' && number_of_lines < 15);
    // var highlighted = validLang ? hljs.highlight(code, { language }).value : code;

    if (show_by_default) {
        return `<div class="code-block">
        <pre><code class="hljs ${language || ''}">${highlighted}</code></pre>
        </div>`;
    }
    else {

    return `<div class="code-block">
        <div class="code-header" style="height: 18px; min-height: 16px; padding: 1px 4px; display: flex; align-items: center; justify-content: space-between;">
            
            <button class="copy-code-btn" style="padding: 2px 2px; font-size: 12px; height: 20px;">Copy</button>
        </div>
        <details style="padding-top: 20px;">
            <summary>Code Block</summary>
            <pre><code class="hljs ${language || ''}">${highlighted}</code></pre>
        </details>
    </div>`;
    }
};

function hasUnclosedMermaidTag(htmlString) {
    // Regular expression to identify all relevant mermaid tags
    // Updated to handle both single and double quotes, and flexible whitespace
    const tagRegex = /<pre\s+class=["']mermaid["']>|<\/pre>|```mermaid|```(?!\w)/g;
    let stack = [];
    let match;

    while ((match = tagRegex.exec(htmlString)) !== null) {
        if (match[0].startsWith("<pre")) {
            // Push the expected closing tag for <pre class='mermaid'> or <pre class="mermaid">
            stack.push("</pre>");
        } else if (match[0] === "```mermaid") {
            // Push the expected closing tag for ```mermaid
            stack.push("```");
        } else if (match[0] === "</pre>" || match[0] === "```") {
            // Check if the closing tag matches the expected one from the stack
            if (stack.length === 0 || stack.pop() !== match[0]) {
                return true; // Mismatch found or stack is empty (unmatched closing tag)
            }
        }
    }

    return stack.length > 0; // If the stack is not empty, there is at least one unclosed tag
}
 
// Function to attach listeners directly to section elements
function attachSectionListeners(elem_to_render_in) {
    $(elem_to_render_in).off('click', 'details summary');
    
    $(elem_to_render_in).on('click', 'details summary', function() {
        // Check if this is a section-details element and handle state persistence
        const sectionDetails = $(this).closest('.section-details');
        var sectionId = $(this).closest('details').attr('id');
        var sectionHash = $(this).closest('details').attr('data-section-hash');
        var detailsElement = $(document.getElementById(sectionId));
        if (sectionDetails.length > 0) {
            const sectionHash = sectionDetails.attr('data-section-hash');
            
            // Use setTimeout to read state after the browser has toggled it
            setTimeout(function() {
                const isOpen = sectionDetails.prop('open');
                const isHidden = !isOpen;
                
                console.log('Section toggled via closest section-details:', sectionHash, 'isHidden:', isHidden);
                
                if (conversation_id && sectionHash) {
                    persistSectionState(conversation_id, sectionHash, isHidden);
                }
            }, 0);
        }
        const details = $(this).parent('details')[0];
        const willBeOpen = !details.hasAttribute('open');
        console.log('details clicked, will be open:', willBeOpen);

    });
}



// Helper function to generate a summary for each section
function generateSectionSummary(sectionContent, sectionIndex) {
    /**
     * Generate a summary title for a section based on its content
     * 
     * @param {string} sectionContent - The markdown content of the section
     * @param {number} sectionIndex - The index of the section (0-based)
     * @returns {string} - A summary title for the section
     */
    
    // Try to extract the first heading if it exists
    var headingMatch = sectionContent.match(/^#{1,6}\s+(.+?)$/m);
    if (headingMatch) {
        return headingMatch[1].trim();
    }
    
    // Try to get the first line of text (non-empty, non-code)
    var lines = sectionContent.split('\n');
    for (var line of lines) {
        line = line.trim();
        line = line.replace(/<answer>/g, '').replace(/<\/answer>/g, '').replace(/\*/g, '');
        // Skip empty lines, code blocks, and special markdown syntax
        if (line && !line.startsWith('```') && !line.startsWith('    ') && !line.startsWith('\t')) {
            // Truncate if too long and add ellipsis
            if (line.length > 50) {
                return line.substring(0, 47) + '...';
            }
            return line;
        }
    }
    
    // Default fallback
    return `Section ${sectionIndex + 1}`;
}

// Add this helper function to handle closing sections
function closeSectionDetails(sectionId) {
    /**
     * Close a specific section details element
     * 
     * @param {string} sectionId - The ID of the details element to close
     */
    var detailsElement = document.getElementById(sectionId);
    if (detailsElement) {
        detailsElement.removeAttribute('open');
        // Optionally scroll to the summary so it's visible after closing
        detailsElement.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
}

// Helper function to fetch and apply section hidden states
function fetchAndApplySectionStates(conversation_id, elem_to_render_in) {
    // Find all section-details elements
    const sectionElements = $(elem_to_render_in).find('.section-details');
    if (sectionElements.length === 0) return;
    
    // Collect section IDs
    const sectionIds = [];
    sectionElements.each(function() {
        const sectionId = $(this).attr('id');
        if (sectionId) {
            // Remove the "section-details-" prefix from the ID
            const cleanedId = sectionId.replace(/^section-details-/, '');
            sectionIds.push(cleanedId);
        }
        
        // if (sectionId) {
        //     // Extract just the hash part of the ID (e.g., "section-details-conv123-abc123" -> "abc123")
        //     const match = sectionId.match(/section-details-[^-]+-(.+)$/);
        //     if (match && match[1]) {
        //         sectionIds.push(match[1]);
        //     }
        // }
    });
    
    if (sectionIds.length === 0) return;
    
    // Fetch hidden states from server
    $.ajax({
        url: '/get_section_hidden_details',
        method: 'GET',
        data: {
            conversation_id: conversation_id,
            section_ids: sectionIds.join(',')
        },
        success: function(response) {
            if (response && response.section_details) {
                // Apply the states to the details elements
                sectionElements.each(function() {
                    const sectionElement = $(this);
                    const sectionId = sectionElement.attr('id');
                    if (sectionId) {
                        const cleanedId = sectionId.replace(/^section-details-/, '');
                        const sectionData = response.section_details[cleanedId];
                        if (sectionData && sectionData.hidden) {
                            // Close the section if it's marked as hidden
                            sectionElement.prop('open', false);
                        }
                        
                    }
                });
            }
        },
        error: function(xhr, status, error) {
            console.error('Failed to fetch section hidden states:', error);
        }
    });
}

// Helper function to persist section state when toggled
function persistSectionState(conversation_id, sectionHash, isHidden) {
    const sectionDetails = {};
    sectionDetails[sectionHash] = { hidden: isHidden };
    
    $.ajax({
        url: '/update_section_hidden_details',
        method: 'POST',
        contentType: 'application/json',
        data: JSON.stringify({
            conversation_id: conversation_id,
            section_details: sectionDetails
        }),
        success: function(response) {
            console.log('Section state persisted:', response);
        },
        error: function(xhr, status, error) {
            console.error('Failed to persist section state:', error);
        }
    });
}

function renderInnerContentAsMarkdown(jqelem, callback = null, continuous = false, html = null, immediate_callback = null) {
    conversation_id = (typeof ConversationManager !== 'undefined' && ConversationManager && ConversationManager.getActiveConversation()!= '') ? ConversationManager.getActiveConversation() : '';
    parent = jqelem.parent()
    elem_id = jqelem.attr('id');
    elem_to_render_in = jqelem
    brother_elem_id = elem_id + "-md-render"
    if (continuous) {
        brother_elem = parent.find('#' + brother_elem_id);
        if (!brother_elem.length) {
            var brother_elem = $('<div/>', { id: brother_elem_id })
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

    // Check if we should wrap sections (you might want to make this configurable)
    var wrapSectionsInDetails = true; // You can make this configurable via options
    // var horizontalRuleRegex = /\n---+\s*\n/g;
    var horizontalRuleRegex = /^---+\s*$/gm;
    var hasHorizontalRules = horizontalRuleRegex.test(html);
    horizontalRuleRegex.lastIndex = 0;

    if (wrapSectionsInDetails && hasHorizontalRules) {
        // Function to extract and protect code blocks before processing
        function extractCodeBlocks(content) {
            var codeBlocks = [];
            var codePlaceholders = [];
            var workingContent = content;
            
            function replaceWithPlaceholder(match) {
                var placeholder = `__CODE_BLOCK_${codeBlocks.length}__`;
                codeBlocks.push(match);
                codePlaceholders.push(placeholder);
                return placeholder;
            }
            
            // Replace all complete fenced code blocks first (``` and ~~~)
            var tripleBacktickRegex = /```[\s\S]*?```/g;
            var tripleTildeRegex = /~~~[\s\S]*?~~~/g;
            workingContent = workingContent.replace(tripleBacktickRegex, replaceWithPlaceholder);
            workingContent = workingContent.replace(tripleTildeRegex, replaceWithPlaceholder);
            
            function isFenceLine(str, idx) {
                var pos = idx - 1;
                while (pos >= 0 && str[pos] !== '\n') {
                    if (str[pos] !== ' ' && str[pos] !== '\t') {
                        return false;
                    }
                    pos--;
                }
                return true;
            }
            
            function protectIncompleteFence(fenceToken) {
                var startIdx = workingContent.lastIndexOf(fenceToken);
                while (startIdx !== -1) {
                    if (isFenceLine(workingContent, startIdx)) {
                        var closingIdx = workingContent.indexOf(fenceToken, startIdx + fenceToken.length);
                        if (closingIdx === -1) {
                            var placeholder = `__CODE_BLOCK_${codeBlocks.length}__`;
                            var segment = workingContent.substring(startIdx);
                            codeBlocks.push(segment);
                            codePlaceholders.push(placeholder);
                            workingContent = workingContent.substring(0, startIdx) + placeholder;
                            break;
                        }
                    }
                    startIdx = workingContent.lastIndexOf(fenceToken, startIdx - 1);
                }
            }
            
            // Protect streaming scenarios where closing fence hasn't arrived yet
            protectIncompleteFence('```');
            protectIncompleteFence('~~~');
            
            // Handle inline code with completed backticks
            workingContent = workingContent.replace(/`[^`\n]+`/g, function(match) {
                var placeholder = `__INLINE_CODE_${codeBlocks.length}__`;
                codeBlocks.push(match);
                codePlaceholders.push(placeholder);
                return placeholder;
            });
            
            // Protect trailing unmatched inline code (e.g., streaming chunk)
            var inlineBacktickCount = (workingContent.match(/`/g) || []).length;
            if (inlineBacktickCount % 2 === 1) {
                var unmatchedIndex = workingContent.lastIndexOf('`');
                if (unmatchedIndex !== -1) {
                    var inlinePlaceholder = `__INLINE_CODE_${codeBlocks.length}__`;
                    var inlineSegment = workingContent.substring(unmatchedIndex);
                    codeBlocks.push(inlineSegment);
                    codePlaceholders.push(inlinePlaceholder);
                    workingContent = workingContent.substring(0, unmatchedIndex) + inlinePlaceholder;
                }
            }
            
            return {
                content: workingContent,
                codeBlocks: codeBlocks,
                placeholders: codePlaceholders
            };
        }
        
        // Function to restore code blocks in content
        function restoreCodeBlocks(content, codeBlocks, placeholders) {
            var restoredContent = content;
            for (var i = 0; i < placeholders.length; i++) {
                restoredContent = restoredContent.replace(placeholders[i], codeBlocks[i]);
            }
            return restoredContent;
        }
        
        // Function to process sections while preserving existing details tags
        function processContentWithDetails(content) {
            // Extract code blocks first to protect them from splitting
            var codeExtraction = extractCodeBlocks(content);
            var contentWithCodePlaceholders = codeExtraction.content;
            var codeBlocks = codeExtraction.codeBlocks;
            var codePlaceholders = codeExtraction.placeholders;
            
            // Now preserve existing <details> tags
            var detailsRegex = /<details[^>]*>[\s\S]*?<\/details>/gi;
            var detailsBlocks = [];
            var placeholders = [];
            
            // Extract and store existing details blocks
            var match;
            var tempContent = contentWithCodePlaceholders;
            while ((match = detailsRegex.exec(contentWithCodePlaceholders)) !== null) {
                var placeholder = `__DETAILS_PLACEHOLDER_${placeholders.length}__`;
                detailsBlocks.push(match[0]);
                placeholders.push(placeholder);
            }
            
            // Replace details blocks with placeholders temporarily
            var workingContent = contentWithCodePlaceholders;
            for (var i = 0; i < detailsBlocks.length; i++) {
                workingContent = workingContent.replace(detailsBlocks[i], placeholders[i]);
            }
            
            // Now split the content by horizontal rules (which are now safe from code blocks)
            var sections = workingContent.split(horizontalRuleRegex);
            horizontalRuleRegex.lastIndex = 0;
            
            if (sections.length > 1) {
                var wrappedHtml = '';
                
                sections.forEach(function(section, sectionIndex) {
                    section = section.trim();
                    
                    // Check if this section contains a details placeholder
                    var hasPlaceholder = placeholders.some(p => section.includes(p));
                    
                    if (hasPlaceholder) {
                        // Process sections that contain placeholders
                        for (var i = 0; i < placeholders.length; i++) {
                            if (section.includes(placeholders[i])) {
                                // Process the content inside the details block recursively
                                var detailsBlock = detailsBlocks[i];
                                var detailsMatch = detailsBlock.match(/<details[^>]*>([\s\S]*?)<\/details>/i);
                                
                                if (detailsMatch) {
                                    var detailsOpening = detailsBlock.match(/<details[^>]*>/)[0];
                                    var detailsContent = detailsMatch[1];
                                    
                                    // Extract code blocks from inner content before processing
                                    var innerCodeExtraction = extractCodeBlocks(detailsContent);
                                    var innerContentWithCodePlaceholders = innerCodeExtraction.content;
                                    var innerCodeBlocks = innerCodeExtraction.codeBlocks;
                                    var innerCodePlaceholders = innerCodeExtraction.placeholders;
                                    
                                    // Check if the inner content has --- horizontal rules (not in code blocks)
                                    var hasHorizontalRules = horizontalRuleRegex.test(innerContentWithCodePlaceholders);
                                    horizontalRuleRegex.lastIndex = 0;
                                    
                                    if (hasHorizontalRules) {
                                        // Process inner content: only wrap sections between --- horizontal rule markers
                                        // Reset regex for splitting since test() advances the lastIndex
                                        var innerSections = innerContentWithCodePlaceholders.split(horizontalRuleRegex);
                                        horizontalRuleRegex.lastIndex = 0;
                                        if (innerSections.length > 1) {
                                            var innerWrapped = '';
                                            
                                            // First section (before first ---) stays as-is
                                            if (innerSections[0].trim()) {
                                                var firstSection = restoreCodeBlocks(innerSections[0].trim(), innerCodeBlocks, innerCodePlaceholders);
                                                // Check if it has a summary tag (from server)
                                                var summaryMatch = firstSection.match(/<summary[^>]*>(.*?)<\/summary>/i);
                                                if (summaryMatch) {
                                                    innerWrapped += firstSection;
                                                } else {
                                                    innerWrapped += firstSection;
                                                }
                                            }
                                            
                                            // Middle sections (between --- markers) get wrapped
                                            for (var j = 1; j < innerSections.length; j++) {
                                                var innerSection = innerSections[j].trim();
                                                if (innerSection) {
                                                    // Restore code blocks in this section before generating summary
                                                    var innerSectionWithCode = restoreCodeBlocks(innerSection, innerCodeBlocks, innerCodePlaceholders);
                                                    var innerSummary = generateSectionSummary(innerSectionWithCode, j - 1);
                                                    // Helper function for hashing
                                                    function simpleHash(str) {
                                                        let hash = 0;
                                                        if (str.length === 0) return hash.toString();
                                                        for (let i = 0; i < str.length; i++) {
                                                            const char = str.charCodeAt(i);
                                                            hash = ((hash << 5) - hash) + char;
                                                            hash = hash & hash;
                                                        }
                                                        return Math.abs(hash).toString(16).substring(0, 8);
                                                    }
                                                    var innerHash = simpleHash(innerSection) || 
                                                        (innerSection.length.toString() + innerSection.replace(/[^a-zA-Z0-9]/g, '').substring(0, 4)).substring(0, 8);
                                                    var innerId = `section-details-${conversation_id}-${innerHash}`;
                                                    
                                                    innerSummary = innerSummary.replace(/<answer>/g, '').replace(/<\/answer>/g, '').replace(/\*/g, '');
                                                    innerWrapped += `
<details open class="section-details nested-section" data-section-index="${j - 1}" data-section-hash="${innerHash}" id="${innerId}">
<summary class="section-summary"><strong>${innerSummary}</strong></summary>
<div class="section-content">

${innerSectionWithCode}

<div class="section-footer">
<button class="close-section-btn btn btn-xs btn-secondary" data-section-id="${innerId}" style="font-size: 10px; padding: 2px 6px;">Close Section</button>
</div>
</div>
</details>`;
                                                }
                                            }
                                            
                                            // Last section (after last ---) stays as-is
                                            var lastSection = innerSections[innerSections.length - 1].trim();
                                            
                                            
                                            detailsBlock = detailsOpening + innerWrapped + '</details>';
                                        }
                                    }
                                    section = section.replace(placeholders[i], detailsBlock);
                                } else {
                                    section = section.replace(placeholders[i], detailsBlocks[i]);
                                }
                            }
                        }
                        // Restore code blocks in the section with restored details
                        section = restoreCodeBlocks(section, codeBlocks, codePlaceholders);
                        wrappedHtml += section;
                    } else {
                        // Handle sections without placeholders
                        // Only wrap if this is a middle section (not first or last)
                        if (sectionIndex === 0) {
                            // First section - don't wrap
                            if (section) {
                                // Restore code blocks before adding to output
                                var sectionWithCode = restoreCodeBlocks(section, codeBlocks, codePlaceholders);
                                wrappedHtml += sectionWithCode + '\n';
                            }
                        } else if (sectionIndex === sections.length - 1) {
                            // Last section - don't wrap
                            if (section) {
                                // Restore code blocks before adding to output
                                var sectionWithCode = restoreCodeBlocks(section, codeBlocks, codePlaceholders);
                                wrappedHtml += '\n' + sectionWithCode;
                            }
                        } else {
                            // Middle section - wrap in details
                            if (section) {
                                // Restore code blocks before generating summary and wrapping
                                var sectionWithCode = restoreCodeBlocks(section, codeBlocks, codePlaceholders);
                                var summary = generateSectionSummary(sectionWithCode, sectionIndex - 1);
                                // Helper function for hashing (if not already defined above)
                                function simpleHash(str) {
                                    let hash = 0;
                                    if (str.length === 0) return hash.toString();
                                    for (let i = 0; i < str.length; i++) {
                                        const char = str.charCodeAt(i);
                                        hash = ((hash << 5) - hash) + char;
                                        hash = hash & hash;
                                    }
                                    return Math.abs(hash).toString(16).substring(0, 8);
                                }
                                var sectionHash = simpleHash(section) || 
                                    (section.length.toString() + section.replace(/[^a-zA-Z0-9]/g, '').substring(0, 4)).substring(0, 8);
                                
                                sectionHash = `${conversation_id}-${sectionHash}`;
                                var sectionId = `section-details-${sectionHash}`;
                                
                                summary = summary.replace(/<answer>/g, '').replace(/<\/answer>/g, '').replace(/\*/g, '');
                                wrappedHtml += `
<details open class="section-details" data-section-index="${sectionIndex - 1}" data-section-hash="${sectionHash}" id="${sectionId}">
    <summary class="section-summary"><strong>${summary}</strong></summary>
    <div class="section-content">
        ${sectionWithCode}
        <div class="section-footer">
            <button class="close-section-btn btn btn-xs btn-secondary" data-section-id="${sectionId}" style="font-size: 10px; padding: 2px 6px;">Close Section</button>
        </div>
    </div>
</details>`;
                            }
                        }
                    }
                });
                
                return wrappedHtml;
            }
            
            // No sections to split, return original content with placeholders restored
            for (var i = 0; i < placeholders.length; i++) {
                workingContent = workingContent.replace(placeholders[i], detailsBlocks[i]);
            }
            // Restore code blocks
            workingContent = restoreCodeBlocks(workingContent, codeBlocks, codePlaceholders);
            return workingContent;
        }
        
        html = processContentWithDetails(html);
    }

    // For the close button, we need to manually track the state change
    $(document).off('click', '.close-section-btn').on('click', '.close-section-btn', function(e) {
        e.preventDefault();
        e.stopPropagation();
        
        var sectionId = $(this).data('section-id');
        var detailsElement = $(document.getElementById(sectionId));
        
        if (detailsElement.length) {
            var sectionHash = detailsElement.attr('data-section-hash');
            
            // Close the details element
            detailsElement.prop('open', false);
            
            // Since programmatic changes don't fire toggle event, manually persist state
            if (conversation_id && sectionHash) {
                persistSectionState(conversation_id, sectionHash, true); // true = hidden
            }
            
            // Smooth scroll to the summary
            detailsElement[0].scrollIntoView({ 
                behavior: 'smooth', 
                block: 'nearest' 
            });
        }
    });
    
    // Check if this input contains slide presentation tags at all
    var hasSlideTags = html.includes('<slide-presentation>');
    var isSlidePresentation = hasSlideTags; // Backward-compatible flag used below
    var htmlChunk;

    if (hasSlideTags) {
        var split = splitSlidePresentationParts(html);
        var combined = '';
        var foundSlide = false;
        for (var pi = 0; pi < split.parts.length; pi++) {
            var part = split.parts[pi];
            if (part.type === 'text') {
                var renderedText = marked.marked(part.content, { renderer: markdownParser });
                renderedText = removeEmTags(renderedText);
                combined += renderedText;
            } else if (part.type === 'slide') {
                foundSlide = true;
                var rawSlideInnerHtml = part.content.trim();
                var fullDocument = isFullHtmlDocument(rawSlideInnerHtml);
                var htmlForBlob;
                if (fullDocument) {
                    htmlForBlob = rawSlideInnerHtml;
                } else {
                    var cleaned = rawSlideInnerHtml
                        .replace(/<script[\s\S]*?<\/script>/gi, '')
                        .replace(/<div[^>]*class=["']?slide-controls[^>]*>[\s\S]*?<\/div>/gi, '');
                    var sectionsOnly = extractSectionsFromReveal(cleaned);
                    htmlForBlob = buildStandaloneSlidesPage(sectionsOnly);
                }
                var blobUrl = createSlidesBlobUrl(htmlForBlob);
                var linkId = 'slide-link-' + Date.now() + '-' + Math.random().toString(36).substr(2, 9);
                
                // Check if inline rendering is enabled
                var renderInline = false;
                try {
                    // Get the current options to check if inline rendering is enabled
                    var options = getOptions('chat-controls', 'assistant');
                    renderInline = options.render_slides_inline || false;
                } catch (e) {
                    console.log('Could not get inline rendering option:', e);
                }
                
                if (renderInline) {
                    // Render both iframe inline and external link
                    var iframeId = 'slide-iframe-' + Date.now() + '-' + Math.random().toString(36).substr(2, 9);
                    combined += `
                        <div class="slide-presentation-container" data-has-slides="true">
                            <div class="slide-external-link mb-3">
                                <a id="${linkId}" href="${blobUrl}" target="_blank" rel="noopener noreferrer">
                                    <i class="bi bi-box-arrow-up-right"></i> Click here to view slides in new window
                                </a>
                            </div>
                            <div class="slide-iframe-wrapper" style="width: 100%; border: 1px solid #dee2e6; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 10px rgba(0, 0, 0, 0.1);">
                                <iframe id="${iframeId}" 
                                        src="${blobUrl}" 
                                        style="width: 100%; height: 600px; border: none; background: #fff;"
                                        allowfullscreen="true"
                                        sandbox="allow-scripts allow-same-origin">
                                </iframe>
                            </div>
                        </div>
                    `;
                } else {
                    // Only show external link
                    combined += `
                        <div class="slide-external-link" data-has-slides="true">
                            <a id="${linkId}" href="${blobUrl}" target="_blank" rel="noopener noreferrer">Click here to see slides</a>
                            <small class="text-muted" style="margin-left: 8px;">(opens in a new window)</small>
                        </div>
                    `;
                }
            }
        }
        if (split.incomplete) {
            // For streaming with an open but not yet closed slide block, render only the text parts before
            // the opening tag. When the closing tag arrives, a subsequent call will render the full content.
        }
        if (foundSlide) {
            try { elem_to_render_in.attr('data-has-slides', 'true'); } catch (e) {}
        }
        htmlChunk = combined;
    } else {
        // Normal markdown processing
        htmlChunk = marked.marked(html, { renderer: markdownParser });
        htmlChunk = removeEmTags(htmlChunk);
    }
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
    // After MathJax finishes, if slides are present, re-adjust card height for accurate layout
    if (isSlidePresentation) {
        MathJax.Hub.Queue(function() {
            try {
                var slideWrapperAfterMath = $(elem_to_render_in).find('.slide-presentation-wrapper');
                if (slideWrapperAfterMath.length > 0) {
                    setTimeout(function() {
                        adjustCardHeightForSlides(slideWrapperAfterMath);
                    }, 50);
                }
            } catch (e) { console.warn('Post-MathJax slide height adjust failed', e); }
        });
    }
    // After MathJax typesetting completes, re-adjust slide/card height if needed
    if (isSlidePresentation) {
        MathJax.Hub.Queue(function() {
            try {
                var slideWrapper = $(elem_to_render_in).find('.slide-presentation-wrapper');
                if (slideWrapper && slideWrapper.length) {
                    adjustCardHeightForSlides(slideWrapper);
                }
            } catch (e) {
                console.log('MathJax post-typeset height adjustment failed:', e);
            }
        });
    }
    // Use Process instead of Queue for immediate execution
    // MathJax.Hub.Process(mathjax_elem);
    // MathJax.Hub.Typeset(mathjax_elem);
    // Option 2: If you want to keep using Process but ensure typesetting
    // MathJax.Hub.processUpdateTime = 0; // Force immediate processing
    // MathJax.Hub.Queue(["Typeset", MathJax.Hub, mathjax_elem]);
    // MathJax.Hub.processUpdateTime = 0; // Force immediate processing
    
    
    if (callback) {
        MathJax.Hub.Queue(callback)
    }

    if (immediate_callback) {
        immediate_callback()
    }
    
    // Add toggle event listeners to section details elements and fetch stored states
    // Only do this for non-streaming content (when we have complete content)

    if (conversation_id && !continuous) {
        // Attach event listeners directly to the section elements
        attachSectionListeners(elem_to_render_in);
        
        // Fetch and apply stored section states (only for non-streaming content)
        fetchAndApplySectionStates(conversation_id, elem_to_render_in);
    }

    

    // Slides are now opened in a new window via link; no in-card Reveal init

    mermaid_rendering_needed = !hasUnclosedMermaidTag(html) && has_end_answer_tag
    code_rendering_needed = $(elem_to_render_in).find('code').length > 0
    drawio_rendering_needed = $(elem_to_render_in).find('.drawio-diagram').length > 0

    if (mermaid_rendering_needed) {
        // last_mermaid = extractLastMermaid(html)
        // if (last_mermaid) {
        //     mermaid_elem = $("<pre class='mermaid'></pre>")
        //     mermaid_elem.text(last_mermaid)
        //     // append as sibling to the possible_mermaid_elem
        //     possible_mermaid_elem.after(mermaid_elem)
        // }
        possible_mermaid_elem = elem_to_render_in.find(".mermaid")
        // if the next element after the possible_mermaid_elem is not a pre element with class mermaid then only render
        render_or_not = possible_mermaid_elem.length & !possible_mermaid_elem.next().hasClass('mermaid') & !possible_mermaid_elem.closest('.code-block').next().hasClass('mermaid')
        // if (render_or_not) {
        //     mermaid_text = possible_mermaid_elem[0].textContent
        //     mermaid_elem = $("<pre class='mermaid'></pre>")
        //     mermaid_elem.text(mermaid_text)
        //     // append as sibling to the possible_mermaid_elem
        //     possible_mermaid_elem.after(mermaid_elem)
        // }
        const mermaidBlocks = elem_to_render_in.parent().find('pre.mermaid');  
        function cleanMermaidCode(mermaidCode) {  
            return mermaidCode  
                .split('\n')  
                .map(line => line.trimRight())  
                .filter(line => line.length > 0 && !line.includes('pre class="mermaid"') && !line.includes('pre class=\'mermaid'))  
                .join('\n');  
        }
        
        if (mermaidBlocks.length > 0) {
            mermaidBlocks.each(function(index, block) {  
                // Get and clean the mermaid code  
                let code = block.textContent || block.innerText;  
                // Only clean code if it hasn't been rendered yet (still contains raw mermaid syntax)
                if (!block.querySelector('svg')) {
                    code = cleanMermaidCode(code);
                    // Update the content directly  
                    block.textContent = code;  
                }
                
            });  

            mermaid.run({
                nodes: mermaidBlocks,
                useMaxWidth: false,
                suppressErrors: false,

            }).then(() => {
                // find all svg inside .mermaid class pre elements.
                var svgs = $(elem_to_render_in).find('pre.mermaid svg');
                // iterate over each svg element and unset its height attribute
                svgs.each(function (index, svg) {
                    $(svg).attr('height', null);
                });
            }).catch(err => {
                console.error('Mermaid Error:', err);
            });
            
        }
    }

    

    if (drawio_rendering_needed) {
        MathJax.Hub.Queue(function() {

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

    return mathjax_elem;
}


function extractLastMermaid(html) {
    /**
     * Extract the last mermaid diagram from the HTML string.
     * 
     * @param {string} html - HTML string that may contain ```mermaid code blocks or <pre class="mermaid"> tags
     * @returns {string} - Extracted Mermaid diagram content (without wrapper tags)
     * 
     * Purpose:
     * Extracts the most recent/last Mermaid diagram from a string that may contain
     * multiple diagrams in either markdown code blocks or HTML pre tags. This is
     * useful for getting the latest diagram when content is being streamed or updated.
     */
    
    // First try to extract from markdown code blocks
    const markdownRegex = /```mermaid(.*?)```/gis;
    const markdownMatches = [];
    let match;
    
    // Find positions of markdown matches
    while ((match = markdownRegex.exec(html)) !== null) {
        markdownMatches.push({
            position: match.index,
            content: match[1].trim()
        });
    }
    
    // Then try to extract from HTML pre tags
    const preTagRegex = /<pre\s+class=["']\s*mermaid\s*["']\s*>(.*?)<\/pre>/gis;
    const preTagMatches = [];
    
    // Reset regex lastIndex for second search
    preTagRegex.lastIndex = 0;
    
    // Find positions of pre tag matches
    while ((match = preTagRegex.exec(html)) !== null) {
        preTagMatches.push({
            position: match.index,
            content: match[1].trim()
        });
    }
    
    // Combine all matches and sort by position
    const allMatches = [...markdownMatches, ...preTagMatches];
    
    if (allMatches.length === 0) {
        return "";
    }
    
    // Sort by position and get the last match
    allMatches.sort((a, b) => a.position - b.position);
    const lastMatchContent = allMatches[allMatches.length - 1].content;
    
    // Validate that it contains Mermaid content (expanded detection)
    if (lastMatchContent && 
        (lastMatchContent.toLowerCase().includes("graph") ||
         lastMatchContent.toLowerCase().includes("flowchart") ||
         lastMatchContent.toLowerCase().includes("sequencediagram") ||
         lastMatchContent.toLowerCase().includes("gitgraph") ||
         lastMatchContent.toLowerCase().includes("classdiagram") ||
         lastMatchContent.toLowerCase().includes("statediagram") ||
         lastMatchContent.toLowerCase().includes("pie") ||
         lastMatchContent.toLowerCase().includes("journey") ||
         lastMatchContent.toLowerCase().includes("erdiagram"))) {
        
        // Clean up content by removing any remaining markdown markers
        return lastMatchContent.replace(/```mermaid/gi, "").replace(/```/g, "").trim();
    }
    
    return "";
}

function renderMermaidIfDetailsTagOpened() {
    // when a <details> tag is opened, we need to run `mermaid.run({querySelector: "pre.mermaid"})`
    // Handle details element toggle events with multiple detection methods for robustness
    $(document).on('toggle', 'details', function() {
        const isOpen = this.hasAttribute('open');
        console.log('details toggled via toggle event, open:', isOpen);
        
        if (isOpen) {
            // Small delay to ensure DOM is updated before running mermaid
            setTimeout(function() {
                mermaid.run({querySelector: "pre.mermaid"});
            }, 50);
        }
    });

    // Fallback: Listen for click events on details/summary elements
    $(document).on('click', 'details summary', function() {
        const details = $(this).parent('details')[0];
        const willBeOpen = !details.hasAttribute('open');
        console.log('details clicked, will be open:', willBeOpen);
        
        if (willBeOpen) {
            // Delay to allow the details to open first
            setTimeout(function() {
                mermaid.run({querySelector: "pre.mermaid"});
            }, 100);
        }
    });

    // Additional fallback: Use MutationObserver to detect attribute changes
    if (typeof MutationObserver !== 'undefined') {
        const observer = new MutationObserver(function(mutations) {
            mutations.forEach(function(mutation) {
                if (mutation.type === 'attributes' && mutation.attributeName === 'open') {
                    const target = mutation.target;
                    if (target.tagName.toLowerCase() === 'details' && target.hasAttribute('open')) {
                        console.log('details opened via MutationObserver');
                        setTimeout(function() {
                            mermaid.run({querySelector: "pre.mermaid"});
                        }, 50);
                    }
                }
            });
        });

        // Observe all details elements for attribute changes
        $(document).on('DOMNodeInserted', function(e) {
            if (e.target.tagName && e.target.tagName.toLowerCase() === 'details') {
                observer.observe(e.target, { attributes: true, attributeFilter: ['open'] });
            }
        });

        // Also observe existing details elements
        $('details').each(function() {
            observer.observe(this, { attributes: true, attributeFilter: ['open'] });
        });
    }
}



function copyToClipboard(textElem, textToCopy, mode = "text") {  
    // Handle CodeMirror editor specifically  
    if (mode === "codemirror") {  
        // Check if it's CodeMirror 5 or 6  
        if (textElem && typeof textElem.getValue === 'function') {  
            // CodeMirror 5 API  
            textToCopy = textElem.getValue();  
            console.log("📋 Using CodeMirror 5 API for copy");  
        } else if (textElem && textElem.state && textElem.state.doc) {  
            // CodeMirror 6 API  
            textToCopy = textElem.state.doc.toString();  
            console.log("📋 Using CodeMirror 6 API for copy");  
        } else {  
            console.error("❌ Invalid CodeMirror editor instance:", textElem);  
            showToast("Failed to access editor content", "error");  
            return false;  
        }  
    }  
    // Your existing logic for other modes  
    else if (mode === "text") {  
        var textElements = $(textElem);  
    }  
    else if (mode === "code") {  
        var textElements = $(textElem).closest('.code-block').find('code');  
    }  
    else {  
        var textElements = $(textElem).find('p, span, div, code, h1, h2, h3, h4, h5, h6, strong, em, input');  
    }  
  
    // if textToCopy is undefined, then we will copy the text from the textElem  
    if (textToCopy === undefined && mode !== "codemirror") {  
        var textToCopy = "";  
        textElements.each(function () {  
            var $this = $(this);  
            if ($this.is("input, textarea")) {  
                textToCopy += $this.val().replace(/\\\[show\\]|\\\[hide\\\]/g, '') + "\n";  
            } else {  
                textToCopy += $this.text().replace(/\\\[show\\\]|\\\[hide\\\]/g, '') + "\n";  
            }  
        });  
    }  
  
    if (navigator.clipboard && navigator.clipboard.writeText) {  
        // New Clipboard API  
        navigator.clipboard.writeText(textToCopy).then(() => {  
            console.log("✅ Text successfully copied to clipboard");  
            showToast("Code copied to clipboard!", "success");  
        }).catch(err => {  
            console.warn("⚠️ Copy to clipboard failed.", err);  
            showToast("Failed to copy code", "error");  
        });  
    } else {  
        // Fallback to the older method for incompatible browsers  
        var textarea = document.createElement("textarea");  
        textarea.textContent = textToCopy;  
        document.body.appendChild(textarea);  
        textarea.select();  
        try {  
            var success = document.execCommand("copy");  
            if (success) {  
                showToast("Code copied to clipboard!", "success");  
            }  
            return success;  
        } catch (ex) {  
            console.warn("⚠️ Copy to clipboard failed.", ex);  
            showToast("Failed to copy code", "error");  
            return false;  
        } finally {  
            document.body.removeChild(textarea);  
        }  
    }  
}  

  
// Simple toast notification function  
function showToast(message, type = "info") {  
    // You can integrate with your existing notification system  
    // For now, using a simple alert - replace with your toast system  
    console.log(`${type.toUpperCase()}: ${message}`);  
    // Example with Bootstrap toast (if you have it):  
    // $('.toast-body').text(message);  
    // $('.toast').toast('show');  
}  




function getOptions(parentElementId, type) {
    checkBoxOptionOne = "googleScholar"
    optionOneChecked = $(type === "assistant" ? `#${parentElementId}-${type}-use-google-scholar` : `#${parentElementId}-${type}-use-references-and-citations-checkbox`).is(':checked');
    slow_fast = `${parentElementId}-${type}-provide-detailed-answers-checkbox`
    values = {
        perform_web_search: $(`#${parentElementId}-${type}-perform-web-search-checkbox`).length ? $(`#${parentElementId}-${type}-perform-web-search-checkbox`).is(':checked') : $('#settings-perform-web-search-checkbox').is(':checked'),
        use_multiple_docs: $(`#${parentElementId}-${type}-use-multiple-docs-checkbox`).length ? $(`#${parentElementId}-${type}-use-multiple-docs-checkbox`).is(':checked') : false,
        tell_me_more: $(`#${parentElementId}-${type}-tell-me-more-checkbox`).length ? $(`#${parentElementId}-${type}-tell-me-more-checkbox`).is(':checked') : false,
        use_memory_pad: $('#use_memory_pad').length ? $('#use_memory_pad').is(':checked') : $('#settings-use_memory_pad').is(':checked'),
        enable_planner: $('#enable_planner').length ? $('#enable_planner').is(':checked') : $('#settings-enable_planner').is(':checked'),
        search_exact: $(`#${parentElementId}-${type}-search-exact`).length ? $(`#${parentElementId}-${type}-search-exact`).is(':checked') : $('#settings-search-exact').is(':checked'),
        ensemble: $(`#${parentElementId}-${type}-ensemble`).length ? $(`#${parentElementId}-${type}-ensemble`).is(':checked') : false,
        persist_or_not: $(`#${parentElementId}-${type}-persist_or_not`).length ? $(`#${parentElementId}-${type}-persist_or_not`).is(':checked') : $('#settings-persist_or_not').is(':checked'),
        ppt_answer: $('#settings-ppt-answer').is(':checked'),
        render_slides_inline: $('#settings-render-slides-inline').is(':checked'),
        only_slides: $('#settings-only-slides').is(':checked'),
        render_close_to_source: $('#settings-render-close-to-source').is(':checked'),
    };
    let speedValue = $("#depthSelector").length ? $("#depthSelector").val() : ($("#settings-depthSelector").val() || '2');
    values['provide_detailed_answers'] = speedValue;
    values[checkBoxOptionOne] = optionOneChecked;
    if (type === "assistant") {
        let historyValue = $("#historySelector").length ? $("#historySelector").val() : ($("#settings-historySelector").val() || '2');
        values['enable_previous_messages'] = historyValue;
        let rewardLevelValue = $("#rewardLevelSelector").length ? $("#rewardLevelSelector").val() : ($("#settings-rewardLevelSelector").val() || '0');
        values['reward_level'] = rewardLevelValue;
    }
    
    if (type === "assistant") {
        // Get preamble options, including custom ones
        let preambleOptions = $('#preamble-selector').length ? 
            $('#preamble-selector').val() : 
            $('#settings-preamble-selector').val();
        
        // If modal hasn't been opened and no value found, check persisted state
        if (!preambleOptions && window.chatSettingsState) {
            preambleOptions = window.chatSettingsState.preamble_options;
        }
        
        values['preamble_options'] = preambleOptions || [];
        values['main_model'] = $('#main-model-selector').length ? $('#main-model-selector').val() : $('#settings-main-model-selector').val();
        values['field'] = $('#field-selector').length ? $('#field-selector').val() : $('#settings-field-selector').val();
        values["permanentText"] = $("#permanentText").length ? $("#permanentText").val() : $("#settings-permanentText").val();
    }
    return values
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

/**
 * Initialize Reveal.js for slide presentations within a container
 * @param {jQuery} container - The container element containing the slide presentation
 */
function initializeSlidePresentation(container) {
    try {
        // Find the slide presentation wrapper
        var slideWrapper = container.find('.slide-presentation-wrapper');
        if (slideWrapper.length === 0) {
            console.error('Slide presentation wrapper not found');
            return;
        }
        
        var slideId = slideWrapper.attr('id');
        if (!slideId) {
            console.error('Slide presentation wrapper has no ID');
            return;
        }
        // Already initialized
        if (slideWrapper.data('revealInstance')) {
            return;
        }
        
        // Check if Reveal.js is available
        if (typeof Reveal === 'undefined') {
            console.error('Reveal.js is not loaded');
            return;
        }
        
        // Find the reveal container within the slide wrapper
        var revealContainer = slideWrapper.find('.reveal');
        if (revealContainer.length === 0) {
            console.error('Reveal container not found in slide presentation');
            return;
        }
        
        // Initialize Reveal.js for this specific container
        // Create a new Reveal instance for this specific container
        var revealInstance = new Reveal(revealContainer[0], {
            embedded: true,
            hash: false,
            controls: true,
            progress: true,
            center: false,
            transition: 'slide',
            backgroundTransition: 'fade',
            plugins: [RevealHighlight, RevealMath.KaTeX]
        });
        
        revealInstance.initialize().then(function() {
            console.log('Reveal.js initialized successfully for slide presentation');
            
            // Add navigation controls if they don't exist
            addSlideNavigationControls(slideWrapper);
            
            // Update slide counter on slide change
            revealInstance.on('slidechanged', function(event) {
                updateSlideCounter(slideWrapper, event.indexh + 1);
                // Re-adjust card height if slide content changes
                setTimeout(function() {
                    adjustCardHeightForSlides(slideWrapper);
                }, 50);
            });
            
            // Initialize slide counter
            var totalSlides = revealInstance.getTotalSlides();
            updateSlideCounter(slideWrapper, 1, totalSlides);
            
            // Store the reveal instance on the wrapper for later use
            slideWrapper.data('revealInstance', revealInstance);
            
            // Ensure the Bootstrap card grows enough to contain the slides
            setTimeout(function() {
                adjustCardHeightForSlides(slideWrapper);
                console.log('Initial card height adjustment completed');
            }, 100);
            
            // Also adjust on window resize
            var resizeHandler = function() { 
                setTimeout(function() {
                    adjustCardHeightForSlides(slideWrapper);
                }, 100);
            };
            slideWrapper.data('resizeHandler', resizeHandler);
            $(window).on('resize', resizeHandler);
            
        }).catch(function(error) {
            console.error('Error initializing Reveal.js:', error);
        });
        
    } catch (error) {
        console.error('Error in initializeSlidePresentation:', error);
    }
}

/**
 * Add navigation controls to slide presentation
 * @param {jQuery} slideWrapper - The slide wrapper element
 */
function addSlideNavigationControls(slideWrapper) {
    // Check if controls already exist
    if (slideWrapper.find('.slide-controls').length > 0) {
        return;
    }
    
    var controlsHtml = `
        <div class="slide-controls mt-3 d-flex justify-content-between align-items-center">
            <button class="btn btn-sm btn-outline-primary slide-prev-btn">
                <i class="bi bi-chevron-left"></i> Previous
            </button>
            <span class="slide-counter-display mx-3">
                <span class="current-slide">1</span> / <span class="total-slides">1</span>
            </span>
            <button class="btn btn-sm btn-outline-primary slide-next-btn">
                Next <i class="bi bi-chevron-right"></i>
            </button>
        </div>
    `;
    
    slideWrapper.append(controlsHtml);
    
    // Add event listeners for navigation buttons
    slideWrapper.find('.slide-prev-btn').on('click', function() {
        var revealInstance = slideWrapper.data('revealInstance');
        if (revealInstance) {
            revealInstance.prev();
        }
    });
    
    slideWrapper.find('.slide-next-btn').on('click', function() {
        var revealInstance = slideWrapper.data('revealInstance');
        if (revealInstance) {
            revealInstance.next();
        }
    });
}

/**
 * Update slide counter display
 * @param {jQuery} slideWrapper - The slide wrapper element
 * @param {number} current - Current slide number (1-based)
 * @param {number} total - Total number of slides (optional)
 */
function updateSlideCounter(slideWrapper, current, total) {
    var currentSlideSpan = slideWrapper.find('.current-slide');
    var totalSlidesSpan = slideWrapper.find('.total-slides');
    
    if (currentSlideSpan.length > 0) {
        currentSlideSpan.text(current);
    }
    
    if (total !== undefined && totalSlidesSpan.length > 0) {
        totalSlidesSpan.text(total);
    }
}

/**
 * Ensure the Bootstrap card is tall enough to fully display slides
 * @param {jQuery} slideWrapper - The slide wrapper element
 */
function adjustCardHeightForSlides(slideWrapper) {
    try {
        var cardBody = slideWrapper.closest('.card-body');
        if (!cardBody.length) { 
            console.log('No card-body found for slide adjustment');
            return; 
        }
        
        // Mark the message card as having slides
        var messageCard = cardBody.closest('.card.message-card');
        if (messageCard.length) {
            messageCard.addClass('has-slides');
            console.log('Added has-slides class to message card');
        }
        
        // Calculate desired height: slide container height + controls + padding
        var wrapperHeight = slideWrapper.outerHeight(true) || 560;
        var controls = slideWrapper.find('.slide-controls');
        var controlsHeight = controls.length ? controls.outerHeight(true) : 40;
        var desired = Math.max(600, wrapperHeight + controlsHeight + 40);
        
        console.log('Adjusting card height - wrapper:', wrapperHeight, 'controls:', controlsHeight, 'desired:', desired);
        
        // Apply min-height and ensure no clipping
        cardBody.css({ 
            'min-height': desired + 'px', 
            'overflow': 'visible',
            'height': 'auto'
        });
        
        // Also ensure the message container allows growth
        if (messageCard.length) {
            messageCard.css({ 
                'overflow': 'visible',
                'min-height': (desired + 20) + 'px',
                'height': 'auto'
            });
        }
        
        // Force a layout recalculation
        setTimeout(function() {
            if (slideWrapper.data('revealInstance')) {
                slideWrapper.data('revealInstance').layout();
            }
        }, 100);
        
    } catch (error) {
        console.error('Error adjusting card height for slides:', error);
    }
}
