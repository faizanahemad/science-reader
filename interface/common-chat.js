// Mobile navbar dropdown proxies → desktop button handlers (R4: deferred — low risk)
deferReady(function() {
    $('#mob-get-chat-transcript').on('click', function(e) { e.preventDefault(); $('#get-chat-transcript').trigger('click'); });
    $('#mob-share-chat').on('click', function(e) { e.preventDefault(); $('#share-chat').trigger('click'); });
    $('#mob-conversation-docs').on('click', function(e) { e.preventDefault(); $('#conversation-docs-button').trigger('click'); });
    $('#mob-global-docs').on('click', function(e) { e.preventDefault(); $('#global-docs-button').trigger('click'); });
    $('#mob-new-temp-chat').on('click', function(e) { e.preventDefault(); $('#new-temp-chat').trigger('click'); });

    // Aside button: open temp LLM chat with current textarea content as the question
    $('#asideButton').on('click', function() {
        var text = $('#messageText').val().trim();
        openAsideChatModal(text);
    });

    // Ctrl+Shift+Space: open aside chat modal (same as aside button)
    $(document).on('keydown.asideShortcut', function(e) {
        if (e.ctrlKey && e.shiftKey && e.code === 'Space') {
            e.preventDefault();
            var text = $('#messageText').val().trim();
            openAsideChatModal(text);
        }
    });
});

// Global variables to track streaming controllers
var currentStreamingController = null;
var currentHintStreamingController = null;
var currentSolutionStreamingController = null;
var currentDoubtStreamingController = null;

/**
 * $chatView — returns the jQuery element for the chat view pane of a given conversation.
 * On mobile (single DOM) or when TabManager is not loaded, falls back to $('#chatView').
 * @param {string} [convId] - conversation ID; defaults to focused tab
 */
function $chatView(convId) {
    if (typeof TabManager === 'undefined' || !TabManager.focusedTabId) return $('#chatView');
    var id = convId || TabManager.focusedTabId;
    var el = document.getElementById('chatView-' + id);
    return el ? $(el) : $('#chatView');
}

var pendingAttachments = [];

// Timer handle for the "already rendering" modal auto-close. Stored at module level
// so it can be cancelled if sendMessageCallback is invoked again before it fires,
// preventing multiple independent 5-second timers from accumulating.
var _preventChatRenderingTimer = null;

function generateThumbnailForMainUI(dataUrl, maxSize) {
    maxSize = maxSize || 100;
    return new Promise(function(resolve) {
        var img = new Image();
        img.onload = function() {
            var canvas = document.createElement('canvas');
            var scale = Math.min(maxSize / img.width, maxSize / img.height, 1);
            canvas.width = img.width * scale;
            canvas.height = img.height * scale;
            var ctx = canvas.getContext('2d');
            ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
            resolve(canvas.toDataURL('image/jpeg', 0.6));
        };
        img.onerror = function() { resolve(null); };
        img.src = dataUrl;
    });
}

function addFileToAttachmentPreview(file, ctx) {
    // ctx (optional): { list: [], container: jQuery } — if omitted, uses globals
    var list = (ctx && ctx.list) ? ctx.list : pendingAttachments;
    var isImage = file.type && file.type.startsWith('image/');
    var attId = Date.now() + '-' + Math.random().toString(16).slice(2);

    if (isImage) {
        var reader = new FileReader();
        reader.onload = function() {
            generateThumbnailForMainUI(reader.result).then(function(thumbnail) {
                list.push({
                    id: attId,
                    name: file.name,
                    type: 'image',
                    thumbnail: thumbnail,
                    doc_id: null,
                    source: null
                });
                renderAttachmentPreviews(ctx);
            });
        };
        reader.readAsDataURL(file);
    } else {
        list.push({
            id: attId,
            name: file.name,
            type: 'file',
            thumbnail: null,
            doc_id: null,
            source: null
        });
        renderAttachmentPreviews(ctx);
    }
    return attId;
}

function enrichAttachmentWithDocInfo(attId, docId, source, title, ctx) {
    var list = (ctx && ctx.list) ? ctx.list : pendingAttachments;
    for (var i = 0; i < list.length; i++) {
        if (list[i].id === attId) {
            list[i].doc_id = docId;
            list[i].source = source;
            if (title) list[i].name = title;
            break;
        }
    }
}

function renderAttachmentPreviews(ctx) {
    var list = (ctx && ctx.list) ? ctx.list : pendingAttachments;
    var container = (ctx && ctx.container) ? ctx.container : $('#attachment-preview');
    if (list.length === 0) {
        container.hide().empty();
        return;
    }
    container.show();
    var html = list.map(function(att) {
        if (att.type === 'image' && att.thumbnail) {
            return '<div class="att-preview" data-id="' + att.id + '">' +
                '<img src="' + att.thumbnail + '" alt="' + (att.name || 'Image') + '">' +
                '<button class="att-remove-btn" title="Remove">&times;</button></div>';
        } else {
            var ext = (att.name || '').split('.').pop().toUpperCase() || 'FILE';
            return '<div class="att-preview att-file" data-id="' + att.id + '">' +
                '<i class="fa fa-file-o"></i> <span class="att-file-name" title="' + (att.name || '') + '">' + ext + '</span>' +
                '<button class="att-remove-btn" title="Remove">&times;</button></div>';
        }
    }).join('');
    container.html(html);

    container.find('.att-remove-btn').off('click').on('click', function() {
        var id = $(this).closest('.att-preview').data('id');
        if (ctx && ctx.list) {
            ctx.list = ctx.list.filter(function(a) { return a.id !== String(id); });
        } else {
            pendingAttachments = pendingAttachments.filter(function(a) { return a.id !== String(id); });
        }
        renderAttachmentPreviews(ctx);
    });
}

function clearAttachmentPreviews(ctx) {
    if (ctx && ctx.list) {
        ctx.list.length = 0;  // mutate in place so callers holding a reference see the reset
    } else {
        pendingAttachments = [];
    }
    renderAttachmentPreviews(ctx);
}

function getDisplayAttachmentsPayload(ctx) {
    var list = (ctx && ctx.list) ? ctx.list : pendingAttachments;
    if (list.length === 0) return null;
    return list.map(function(a) {
        return { type: a.type, name: a.name, thumbnail: a.thumbnail, doc_id: a.doc_id || null, source: a.source || null };
    });
}

/**
 * Upload a single file to /attach_doc_to_message and add it to the attachment
 * preview strip.  Works for both the main chat (no ctx) and the doubt / temp-LLM
 * modals (pass ctx = { list, container }).
 *
 * @param {File} file
 * @param {string} conversationId
 * @param {Object|null} ctx  Optional context: { list: [], container: jQuery }
 */
function uploadFileToConversation(file, conversationId, ctx) {
    if (!conversationId) {
        showToast('No active conversation — cannot attach file.', 'warning');
        return;
    }
    var attId = addFileToAttachmentPreview(file, ctx);

    var formData = new FormData();
    formData.append('pdf_file', file);

    $.ajax({
        url: '/attach_doc_to_message/' + conversationId,
        type: 'POST',
        data: formData,
        processData: false,
        contentType: false,
        success: function(resp) {
            if (resp && resp.doc_id) {
                enrichAttachmentWithDocInfo(attId, resp.doc_id, resp.source || null, resp.title || null, ctx);
                renderAttachmentPreviews(ctx);
            }
        },
        error: function(xhr) {
            var msg = 'Failed to attach file.';
            try { msg = JSON.parse(xhr.responseText).error || msg; } catch(e) {}
            showToast(msg, 'danger');
            // Remove the failed entry from the preview
            if (ctx && ctx.list) {
                ctx.list = ctx.list.filter(function(a) { return a.id !== attId; });
            } else {
                pendingAttachments = pendingAttachments.filter(function(a) { return a.id !== attId; });
            }
            renderAttachmentPreviews(ctx);
        }
    });
}

/**
 * Render attachment thumbnails/badges from a display_attachments array into a
 * jQuery container.  Used to show attachments on loaded doubt cards and message
 * cards after reload.
 *
 * @param {Array} displayAttachments  Array of {type, name, thumbnail, doc_id, source}
 * @param {jQuery} $container  Where to append the rendered elements
 * @param {string} conversationId  For context-menu actions
 */
function renderDisplayAttachmentBadges(displayAttachments, $container, conversationId) {
    if (!displayAttachments || displayAttachments.length === 0) return;
    var $wrap = $('<div class="message-attachments"></div>');
    displayAttachments.forEach(function(att) {
        var $el;
        if (att.type === 'image' && att.thumbnail) {
            $el = $('<img class="msg-att-thumb">').attr('src', att.thumbnail).attr('alt', att.name || 'Image').attr('title', att.name || 'Image');
        } else {
            var isPdf = (att.name || '').toLowerCase().endsWith('.pdf');
            var iconClass = isPdf ? 'fa fa-file-pdf-o' : 'fa fa-file-o';
            $el = $('<span class="msg-att-badge"><i class="' + iconClass + '"></i> ' + (att.name || 'File') + '</span>');
        }
        $el.addClass('msg-att-clickable');
        $el.on('click', function(e) {
            e.stopPropagation();
            showAttachmentContextMenu(e, att, conversationId);
        });
        $wrap.append($el);
    });
    $container.append($wrap);
}

function showAttachmentContextMenu(event, att, conversationId) {
    $('.att-context-menu').remove();
    var isPdf = (att.name || '').toLowerCase().endsWith('.pdf');
    var hasDocId = !!att.doc_id;
    var hasSource = !!att.source;
    var items = [];

    if (isPdf && hasSource) {
        items.push('<div class="att-ctx-item" data-action="preview"><i class="fa fa-eye"></i> Preview</div>');
    }
    if (hasDocId) {
        items.push('<div class="att-ctx-item" data-action="download"><i class="fa fa-download"></i> Download</div>');
    }
    if (hasDocId) {
        items.push('<div class="att-ctx-item" data-action="add-to-conv"><i class="fa fa-plus-circle"></i> Add to Conversation</div>');
    }
    items.push('<div class="att-ctx-item" data-action="attach-turn"><i class="fa fa-paperclip"></i> Attach for current turn</div>');
    if (items.length === 0) {
        items.push('<div class="att-ctx-item att-ctx-disabled"><i class="fa fa-info-circle"></i> No actions available</div>');
    }

    var $menu = $('<div class="att-context-menu">' + items.join('') + '</div>');
    $('body').append($menu);

    var x = event.pageX, y = event.pageY;
    if (x + $menu.outerWidth() > $(window).width()) x = $(window).width() - $menu.outerWidth() - 10;
    if (y + $menu.outerHeight() > $(window).height() + $(window).scrollTop()) y = y - $menu.outerHeight();
    $menu.css({ left: x, top: y });

    $menu.find('[data-action="preview"]').on('click', function() {
        $menu.remove();
        showPDF(att.source, "chat-pdf-content", "/proxy_shared");
        $("#chat-pdf-content").removeClass('d-none');
        ChatManager.shownDoc = att.source;
    });
    $menu.find('[data-action="download"]').on('click', function() {
        $menu.remove();
        window.open('/download_doc_from_conversation/' + conversationId + '/' + att.doc_id, '_blank');
    });
    $menu.find('[data-action="add-to-conv"]').on('click', function() {
        $menu.remove();
        var $btn = $(this);
        showToast('Promoting document to conversation (this may take a moment)...', 'info');
        $.ajax({
            url: '/promote_message_doc/' + conversationId + '/' + att.doc_id,
            method: 'POST',
            contentType: 'application/json',
            success: function(resp) {
                showToast('Document promoted to conversation: ' + (resp.title || att.name), 'success');
                LocalDocsManager.refresh(conversationId);
            },
            error: function(xhr) {
                var msg = 'Failed to promote document.';
                try { msg = JSON.parse(xhr.responseText).error || msg; } catch(e) {}
                showToast(msg, 'danger');
            }
        });
    });
    $menu.find('[data-action="attach-turn"]').on('click', function() {
        $menu.remove();
        var newId = 'reattach_' + Date.now();
        var entry = {
            id: newId,
            file: null,
            name: att.name || 'attachment',
            type: att.type || 'pdf',
            thumbnail: att.thumbnail || null,
            doc_id: att.doc_id || null,
            source: att.source || null,
            title: att.name || ''
        };
        pendingAttachments.push(entry);
        renderAttachmentPreviews();
        showToast('Attached for current turn: ' + entry.name, 'info');
    });

    $(document).one('click', function() { $menu.remove(); });
}

var ConversationManager = {
    activeConversationId: null,
    activeConversationFriendlyId: '',
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

    statelessConversation: function (conversationId, suppressModal) {
        return $.ajax({
            url: '/make_conversation_stateless/' + conversationId,
            type: 'DELETE',
            success: function (result) {
                if (suppressModal) return;
                if (result.stateless === false) {
                    $('#stateful-conversation-modal').modal('show');
                } else {
                    if (currentDomain['domain'] === 'assistant' || currentDomain['domain'] === 'finance') {
                        $('#stateless-conversation-modal').modal('show');
                    }
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
        // IMPORTANT: Capture all parameters as local constants to avoid shared state issues.
        // This prevents bugs where editing multiple cards can cause the wrong card to be updated.
        const savedText = text;
        const savedMessageId = message_id;
        const savedIndex = index;
        const savedCard = card;
        const activeConversationId = this.activeConversationId;
        
        return $.ajax({
            url: '/edit_message_from_conversation/' + activeConversationId + '/' + savedMessageId + '/' + savedIndex,
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ 'text': savedText }),  
            success: function (result) {
                // Rerender the card - use local variables to ensure correct card is updated
                const answer = savedText;
                const answerParagraph = savedCard.find('.actual-card-text').last();
                if (answerParagraph.length) {
                    renderInnerContentAsMarkdown(answerParagraph, function () {
                        // Callback after rendering
                    }, false, answer);
                    initialiseVoteBank(savedCard, answer, null, ConversationManager.activeConversationId);
                }
                // Drop the stale rendered-HTML snapshot so a reload re-renders the
                // edited text from the server instead of restoring old markup.
                try {
                    if (window.RenderedStateManager && window.RenderedStateManager.invalidate) {
                        window.RenderedStateManager.invalidate(activeConversationId);
                    }
                } catch (_e) { /* best-effort */ }
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
                if (typeof showToast === 'function') { showToast('Error loading conversation details', 'danger'); } else { console.error('Error loading conversation details:', result.responseText); }
            }
        });
    },

    getConversationSettings: function () {
        conversationId = this.activeConversationId
        return $.ajax({
            url: '/get_conversation_settings/' + conversationId,
            type: 'GET',
            success: function (result) {
                return result;
            },
            error: function (result) {
                console.error('Error fetching conversation settings:', result.responseText);
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
        var _sacT = _perfStart('setActiveConversation');
        _perfReset();  // clear previous timings for fresh measurement
        // Cancel any pending MathJax typesetting from the previous conversation
        if (window._mathJaxScheduler) { _mathJaxScheduler.clear(); }
        if (window._PERF) { window._perfFullyInteractiveStart = performance.now(); }
        function _lastConversationStorageKey() {
            /**
             * Persisted "resume last chat" key.
             * Scopes by user email + current domain when available, but degrades gracefully.
             */
            try {
                const email =
                    (typeof userDetails !== 'undefined' && userDetails && userDetails.email)
                        ? String(userDetails.email)
                        : 'unknown';
                const domain =
                    (typeof currentDomain !== 'undefined' && currentDomain && currentDomain['domain'])
                        ? String(currentDomain['domain'])
                        : 'unknown';
                return `lastActiveConversationId:${email}:${domain}`;
            } catch (_e) {
                return 'lastActiveConversationId:unknown:unknown';
            }
        }

        // Option 3: If user selects the already-active conversation, don't re-fetch/re-render.
        // Just close the sidebar on mobile and return.
        try {
            if (this.activeConversationId && String(this.activeConversationId) === String(conversationId)) {
                try {
                    if (window.innerWidth < 768) {
                        var sidebar = $('#chat-assistant-sidebar');
                        var contentCol = $('#chat-assistant');
                        if (sidebar.length && contentCol.length && !sidebar.hasClass('d-none')) {
                            sidebar.addClass('d-none');
                            contentCol.removeClass('col-md-9').addClass('col-md-12');
                            $(window).trigger('resize');
                        }
                    }
                } catch (_e) { /* ignore */ }
                return;
            }
        } catch (_e) { /* ignore */ }

        // Check if conversation exists in the loaded conversation list.
        // This guards against trying to load a deleted temporary conversation.
        var _convExistsInList = true;
        try {
            if (typeof WorkspaceManager !== 'undefined' && WorkspaceManager.conversations && WorkspaceManager.conversations.length > 0) {
                _convExistsInList = WorkspaceManager.conversations.some(function (c) {
                    return String(c.conversation_id) === String(conversationId);
                });
            }
        } catch (_e) { /* ignore */ }

        if (!_convExistsInList) {
            // Conversation was deleted (likely a temporary conversation).
            // Clear stale localStorage and notify user.
            try { localStorage.removeItem(_lastConversationStorageKey()); } catch (_e) { /* ignore */ }
            if (typeof showToast === 'function') {
                showToast('This conversation is no longer available. It may have been a temporary conversation that was cleaned up.', 'warning');
            }
            // Try to fall back to the first available conversation
            try {
                if (typeof WorkspaceManager !== 'undefined' && WorkspaceManager.conversations && WorkspaceManager.conversations.length > 0) {
                    var fallbackId = WorkspaceManager.conversations[0].conversation_id;
                    if (fallbackId && String(fallbackId) !== String(conversationId)) {
                        ConversationManager.setActiveConversation(fallbackId);
                        WorkspaceManager.highlightActiveConversation(fallbackId, true);
                    }
                }
            } catch (_e) { /* ignore */ }
            return;
        }

        this.activeConversationId = conversationId;
        // Reset PKB recent turns ring buffer when switching conversations
        // so context from the old conversation doesn't bleed into the new one.
        try { ConversationManager.recentTurns = []; } catch (_e) {}
        // Set the conversation_friendly_id from WorkspaceManager's cached conversation data
        this.activeConversationFriendlyId = '';
        try {
            if (typeof WorkspaceManager !== 'undefined' && WorkspaceManager.conversations) {
                var convData = WorkspaceManager.conversations.find(function (c) {
                    return c.conversation_id === conversationId;
                });
                if (convData && convData.conversation_friendly_id) {
                    this.activeConversationFriendlyId = convData.conversation_friendly_id;
                }
            }
        } catch (_e) { /* ignore */ }
        // Resume-on-open: record the last active conversation id so `/interface/` can reopen it.
        try {
            localStorage.setItem(_lastConversationStorageKey(), String(conversationId));
        } catch (_e) { /* ignore */ }
        updateUrlWithConversationId(conversationId);

        // Mobile UX: when selecting a conversation from the sidebar, reliably hide it
        // (not toggle). WorkspaceManager.hideSidebarIfMobile is the canonical implementation.
        if (typeof WorkspaceManager !== 'undefined' && WorkspaceManager.hideSidebarIfMobile) {
            WorkspaceManager.hideSidebarIfMobile();
        }

        // Rendered-state persistence:
        // - Try to restore a DOM snapshot for instant paint.
        // - Fetch messages from API (NetworkOnly) and only re-render if conversation changed
        //   compared to snapshot meta (last message id + count).
        var restorePromise = null;
        try {
            restorePromise = (window.RenderedStateManager && window.RenderedStateManager.restore)
                ? window.RenderedStateManager.restore(conversationId)
                : null;
        } catch (_e) { restorePromise = null; }

        if (!restorePromise) {
            restorePromise = $.Deferred().resolve(null).promise();
        }

        var messagesRequest = ChatManager.listMessages(conversationId, true);
        var _networkT = _perfStart('networkWait');

        // R2: Fetch-early / apply-late — fire doubts + pins network requests NOW
        // so they overlap with the messages API call.  Previously these were inside
        // the $.when callback, meaning they waited for messages to return before
        // starting (~200-500ms of wasted network latency).
        // The apply step still waits for _renderCompletePromise (all cards in DOM).
        var _r2ConvId = conversationId;  // capture for stale-response guard
        var _doubtsNetT = _perfStart('doubtsFetch');
        var doubtsPromise = _fetchDoubtsData(conversationId);
        doubtsPromise.then(function() { _perfEnd('doubtsFetch', _doubtsNetT); });
        var _pinsNetT = _perfStart('pinsFetch');
        var pinsPromise = ChatManager._fetchPinsData(conversationId);
        Promise.resolve(pinsPromise).then(function() { _perfEnd('pinsFetch', _pinsNetT); });

        $.when(restorePromise, messagesRequest).done(function (snapshotMeta, messages) {
            _perfEnd('networkWait', _networkT);
            // When used inside $.when, a jQuery.ajax success value becomes:
            //   messages = [data, statusText, jqXHR]
            // where `data` is either the message array (legacy shape) or, with
            // include_ui_state=true, an object { messages, section_details }.
            var payload = messages;
            try {
                if (Array.isArray(messages) && messages.length === 3 && typeof messages[1] === 'string') {
                    payload = messages[0];
                }
            } catch (_e) { payload = messages; }

            var msgList = [];
            var sectionDetails = {};
            try {
                if (Array.isArray(payload)) {
                    // Legacy bare-array shape.
                    msgList = payload;
                } else if (payload && typeof payload === 'object') {
                    if (Array.isArray(payload.messages)) {
                        msgList = payload.messages;
                        sectionDetails = payload.section_details || {};
                    } else if (Array.isArray(payload[0])) {
                        msgList = payload[0];
                    }
                }
            } catch (_e) {
                msgList = [];
            }

            // Populate the UI-state cache BEFORE rendering so section/answer collapse
            // is applied synchronously at render time (no expand-then-collapse flash)
            // and so the debounced fetchConversationUIState / snapshot restore can read
            // it instead of making a second backend call.
            try {
                if (window.ConversationUIState) {
                    window.ConversationUIState.setFromList(conversationId, msgList, sectionDetails);
                }
            } catch (_e) { /* ignore */ }

            // Disconnect observers from previous conversation's cards before we either
            // re-render or paint over with a snapshot. The snapshot-restore path previously
            // skipped this, leaving observers attached to detached DOM nodes.
            try { cleanupMessageObservers(); } catch (_e) { /* ignore */ }

            var keepSnapshot = false;
            try {
                if (snapshotMeta && window.RenderedStateManager && window.RenderedStateManager.matchesMessages) {
                    keepSnapshot = window.RenderedStateManager.matchesMessages(snapshotMeta, msgList);
                }
            } catch (_e) { keepSnapshot = false; }

            if (!keepSnapshot) {
                ChatManager.renderMessages(conversationId, msgList, true);
            } else {
                // Cancel any in-progress chunked render before painting snapshot.
                _renderGeneration++;
                // R2: Snapshot path — all cards are already in the live DOM.
                // Reset and immediately resolve the render-complete promise so
                // fetch-early / apply-late chains don't hang.
                _resetRenderCompletePromise();
                if (typeof _renderCompleteResolve === 'function') {
                    _renderCompleteResolve();
                }
                // REMOVED: Auto-focus on messageText causes soft keyboard on mobile/tablet.
                // try { $('#messageText').focus(); } catch (_e) {}
                // Restore section hidden states + message show/hide via unified endpoint.
                // renderInnerContentAsMarkdown was skipped, so the normal debounced call didn't run.
                // Clear the applied flag first — snapshot HTML did NOT go through the synchronous
                // per-card apply, so fetchConversationUIState must actually run.
                try {
                    if (window.ConversationUIState && typeof window.ConversationUIState.clearApplied === 'function') {
                        window.ConversationUIState.clearApplied(conversationId);
                    }
                } catch (_e) { /* ignore */ }
                try {
                    if (conversationId && !MOCK_SECTION_STATE_API) {
                        var $cv = $chatView(conversationId);
                        fetchConversationUIState(conversationId, $cv[0]);
                    }
                } catch (_e) { /* ignore */ }

                // Re-initialize vote banks for all snapshot-restored cards.
                // The snapshot restores HTML but NOT JS event handlers (initialiseVoteBank
                // was never called on these elements), so copy buttons and triple-dot
                // dropdown menus would be broken without this re-initialization.
                try {
                    var _msgMap = {};
                    msgList.forEach(function(msg) {
                        if (msg.message_id) { _msgMap[String(msg.message_id)] = msg; }
                    });
                    $chatView(conversationId).find('.message-card').each(function() {
                        var $card = $(this);
                        var msgId = $card.find('.history-message-checkbox').attr('message-id');
                        var msg = _msgMap[String(msgId)];
                        if (msg && msg.text && msg.text.trim().length > 0) {
                            var _disable = (msg.sender === 'user');
                            initialiseVoteBank($card, msg.text, msg.message_id, conversationId, _disable);
                        }
                    });
                } catch (_reinit_err) { /* ignore */ }
            }

            // REMOVED: Auto-focus on messageText causes soft keyboard on mobile/tablet.
            // $('#messageText').focus();
            $("#show-sidebar").focus();
            // R2: Apply-late — doubts + pins network requests were already fired
            // above (before $.when), overlapping with the messages API call.
            // Here we just wire up the apply step, which waits for both the
            // fetch AND _renderCompletePromise (all cards in live DOM).
            Promise.all([doubtsPromise, _renderCompletePromise]).then(function (results) {
                // Stale-response guard: if user switched conversations, discard
                if (ConversationManager.activeConversationId !== _r2ConvId) return;
                console.log('[DOUBTS-DIAG] Promise.all resolved, about to apply. messageIds count:', (results[0] || []).length);
                console.log('[DOUBTS-DIAG] .has-doubts-btn count:', $('.has-doubts-btn').length);
                var _applyDT = _perfStart('applyDoubts');
                _applyDoubtsToCards(results[0], false);
                _perfEnd('applyDoubts', _applyDT);
            });
            // Wrap jQuery Deferred in native Promise for safe interop
            Promise.all([Promise.resolve(pinsPromise), _renderCompletePromise]).then(function () {
                // Stale-response guard
                if (ConversationManager.activeConversationId !== _r2ConvId) return;
                var _applyPT = _perfStart('applyPins');
                ChatManager._applyPinsToCards();
                _perfEnd('applyPins', _applyPT);
            });
            // Item 3.3: hide loader — covers both the renderMessages path (which
            // hides inside _runPostRenderWork) and the snapshot-restore path.
            try { $("#loader").hide(); } catch (_e) { /* ignore */ }
            _perfEnd('setActiveConversation', _sacT);
        }).fail(function () {
            // API call failed (e.g. 404 for deleted conversation).
            // Clear stale state and fall back gracefully.
            try { localStorage.removeItem(_lastConversationStorageKey()); } catch (_e) { /* ignore */ }
            if (typeof showToast === 'function') {
                showToast('Could not load conversation. It may have been deleted.', 'warning');
            }
            try {
                if (typeof WorkspaceManager !== 'undefined' && WorkspaceManager.conversations && WorkspaceManager.conversations.length > 0) {
                    var fallbackId = WorkspaceManager.conversations[0].conversation_id;
                    if (fallbackId && String(fallbackId) !== String(conversationId)) {
                        ConversationManager.setActiveConversation(fallbackId);
                        WorkspaceManager.highlightActiveConversation(fallbackId, true);
                    }
                }
            } catch (_e) { /* ignore */ }
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
        this.getConversationSettings().done(function (conversationSettings) {
            if (conversationSettings && conversationSettings.settings) {
                ConversationManager.conversationSettings = conversationSettings.settings;
            } else {
                ConversationManager.conversationSettings = {};
            }
            if (ConversationManager.conversationSettings.model_overrides) {
                if (!window.chatSettingsState) {
                    window.chatSettingsState = {};
                }
                window.chatSettingsState.model_overrides = ConversationManager.conversationSettings.model_overrides;
            }
        });
        this.fetchMemoryPad().fail(function () {
            if (typeof showToast === 'function') { showToast('Error fetching memory pad', 'danger'); } else { console.error('Error fetching memory pad'); }
        });
        LocalDocsManager.refresh(conversationId);
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
 * Check whether the given text currently ends inside an unclosed display math block.
 *
 * Handles both $$...$$ and \\[...\\] (escaped bracket) display math delimiters.
 * Code blocks (``` fenced) are excluded from the check so that math delimiters
 * inside code are not counted.
 *
 * Purpose:
 *   During streaming, we want to SKIP rendering while inside an incomplete
 *   display math block.  Rendering partial math causes MathJax to flash raw
 *   delimiters and triggers layout reflow.  By deferring the render until the
 *   math block closes, the user sees the fully-typeset equation in one step.
 *
 * How it works:
 *   1. Strip out complete code blocks (```...```) so delimiters inside code
 *      are not counted.
 *   2. Handle dangling (unclosed) code fences by removing everything from the
 *      last unmatched ``` to the end.
 *   3. Count unmatched \\[ vs \\] and odd $$ occurrences to determine whether
 *      a display math block is still open.
 *
 * @param {string} text - The accumulated text to check
 * @returns {boolean} true if text ends inside an unclosed display math block
 */
function isInsideDisplayMath(text) {
    if (!text) return false;

    // 1. Remove complete fenced code blocks so their content is ignored
    var textNoCode = text.replace(/```[\s\S]*?```/g, '');

    // 2. Handle incomplete (streaming) code fences: if an odd number of ```
    //    remains, remove from the last ``` to the end (that's still inside code)
    var fenceCount = (textNoCode.match(/```/g) || []).length;
    if (fenceCount % 2 !== 0) {
        var lastFence = textNoCode.lastIndexOf('```');
        if (lastFence !== -1) {
            textNoCode = textNoCode.substring(0, lastFence);
        }
    }

    // 3. Check for unmatched \\[ without \\]
    //    In the runtime string \\[ is the 3-char sequence: backslash, backslash, [
    //    Regex /\\\\\[/g  matches exactly that.
    var bracketOpenCount  = (textNoCode.match(/\\\\\[/g) || []).length;
    var bracketCloseCount = (textNoCode.match(/\\\\\]/g) || []).length;
    if (bracketOpenCount > bracketCloseCount) return true;

    // 4. Check for unmatched $$ (odd count means one is still open)
    var doubleDollarCount = (textNoCode.match(/\$\$/g) || []).length;
    if (doubleDollarCount % 2 !== 0) return true;

    return false;
}


/**
 * Detects the last valid breakpoint in text and returns sections before and after it.
 * 
 * Protected environments (no breaks inside):
 * - Code blocks (between triple backticks ```)
 * - Math display blocks (between $$ delimiters)
 * - Display math blocks (between \\[ and \\] delimiters)
 * - Details elements (between <details> and </details> tags)
 * - Inline math ($...$) within paragraphs
 * 
 * Valid breakpoints (in priority order):
 * - Before markdown headers (# ## ###)
 * - After horizontal rules (---)
 * - After completed display math blocks (\\] or closing $$)
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
    let inMathBlock = false;           // $$ display math
    let inDisplayMathBracket = false;  // \\[...\\] display math
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
        
        // ── \\[...\\] display math tracking ──────────────────────────
        // In the runtime string, display math opening is the 3-char sequence
        // backslash + backslash + [ (written as '\\\\[' in JS source).
        // The backend's ensure_display_math_newlines() puts these on their own
        // lines, so typically trimmedLine === '\\\\[' or '\\\\]'.
        const hasDisplayOpen  = trimmedLine.includes('\\\\[');
        const hasDisplayClose = trimmedLine.includes('\\\\]');
        
        if (inDisplayMathBracket) {
            if (hasDisplayClose) {
                inDisplayMathBracket = false;
                // Display math just closed — excellent breakpoint
                if (i > 2 && !inList && !inBlockquote) {
                    lastBreakpointIndex = i + 1;  // break AFTER closing line
                    breakpointType = "after-display-math-bracket";
                }
            }
            // While inside \\[...\\], skip all other breakpoint logic
            continue;
        } else {
            if (hasDisplayOpen && !hasDisplayClose) {
                // Opening \\[ without a closing \\] on the same line
                inDisplayMathBracket = true;
                continue;
            } else if (hasDisplayOpen && hasDisplayClose) {
                // Complete display math on one line (e.g. \\[E=mc^2\\])
                // Good breakpoint after this line
                if (i > 2 && !inList && !inBlockquote) {
                    lastBreakpointIndex = i + 1;
                    breakpointType = "after-display-math-bracket";
                }
                // Don't set inDisplayMathBracket — the block is already closed
            }
        }
        
        // ── $$ display math tracking ─────────────────────────────────
        // Count $$ occurrences in the line
        const doubleDollarCount = (trimmedLine.match(/\$\$/g) || []).length;
        
        // Handle math blocks that span multiple lines
        if (doubleDollarCount % 2 === 1) {
            // Odd number means we're toggling math block state
            inMathBlock = !inMathBlock;
            if (inMathBlock) {
                mathBlockStart = i;
            } else {
                // $$ display math just closed — good breakpoint
                if (i > 2 && !inList && !inBlockquote) {
                    lastBreakpointIndex = i + 1;  // break AFTER closing line
                    breakpointType = "after-display-math-dollar";
                }
            }
        } else if (doubleDollarCount > 0 && doubleDollarCount % 2 === 0) {
            // Even number of $$ means complete math expressions on one line
            // This line contains complete math, safe to break after it
            if (i > 2 && !inList && !inBlockquote) {
                lastBreakpointIndex = i + 1;
                breakpointType = "after-display-math-dollar";
            }
        }
        
        // Skip if we're inside a $$ math block
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
        if (!inCodeBlock && !inMathBlock && !inDisplayMathBracket && !inDetailsBlock && !inList) {
            
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
                const isAfterMath = prevLine.includes('$$') || prevLine.endsWith('$')
                    || prevLine.includes('\\\\]');
                const isBeforeMath = i + 2 < lines.length && 
                    (lines[i + 2].trim().startsWith('$$') || lines[i + 2].trim().startsWith('$')
                     || lines[i + 2].trim().startsWith('\\\\['));
                
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
    
    // $$ display math: odd count means unclosed
    const mathBlockMatches = text.match(/\$\$/g) || [];
    const hasUnclosedMathBlock = mathBlockMatches.length % 2 !== 0;
    
    // \\[...\\] display math: more opens than closes means unclosed
    const displayMathOpenCount  = (text.match(/\\\\\[/g) || []).length;
    const displayMathCloseCount = (text.match(/\\\\\]/g) || []).length;
    const hasUnclosedDisplayMathBracket = displayMathOpenCount > displayMathCloseCount;
    
    const detailsOpenCount = (text.match(/<details[^>]*>/g) || []).length;
    const detailsCloseCount = (text.match(/<\/details>/g) || []).length;
    const hasUnclosedDetails = detailsOpenCount > detailsCloseCount;
    
    // Don't create breakpoints if we have unclosed structures
    if (hasUnclosedCodeBlock || hasUnclosedMathBlock || hasUnclosedDisplayMathBracket || hasUnclosedDetails) {
        var unclosedType = hasUnclosedCodeBlock ? 'code' 
            : hasUnclosedMathBlock ? 'math-dollar' 
            : hasUnclosedDisplayMathBracket ? 'math-bracket' 
            : 'details';
        return { 
            hasBreakpoint: false, 
            textAfterBreakpoint: text,
            reason: 'Unclosed structure: ' + unclosedType
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
        
        // console.log('Found breakpoint at line ' + lastBreakpointIndex + ' (type: ' + breakpointType + ')');
        
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
    // Cancel any in-progress chunked render — streaming needs exclusive DOM access.
    // Incrementing the generation token causes pending _renderChunk() calls to bail.
    _renderGeneration++;

    // Remove any existing suggestions when starting a new response
    $chatView().find('.next-question-suggestions').remove();
    
    // Show stop button and hide send button
    $('#stopResponseButton').show();
    $('#sendMessageButton').hide();
    
    // Reset tool call manager state for the new response
    if (typeof ToolCallManager !== 'undefined') {
        ToolCallManager.reset();
    }
    
    var reader = streamingResponse.body.getReader();
    var decoder = new TextDecoder();
    let buffer = '';
    let card = null;
    let answerParagraph = null;
    let elem_to_render = null;
    // Perf: cache statusDiv and spinner jQuery references so we don't
    // re-query the DOM on every streaming chunk (saves ~200-400 .find() calls).
    let _cachedStatusDiv = null;
    let _cachedSpinner = null;
    var content_length = 0;
    // Tracks whether the current section's latest rendered_answer has already been
    // passed to renderInnerContentAsMarkdown. Used to avoid the O(N²)
    // rendered_till_now.includes(rendered_answer) substring scan.
    var _section_already_rendered = false;
    // Tracks whether the current section has seen any display-math delimiter ($$, \\[, \\]).
    // Set to true on the first chunk that contains one; reset on every section boundary.
    // Used to skip the expensive isInsideDisplayMath() call (5 regex passes on the full
    // accumulated string) for sections that contain no math at all.
    var _section_has_display_math = false;
    // Cache for getTextAfterLastBreakpoint. The function splits the full
    // rendered_answer by \n and scans every line — O(lines) per chunk.
    // Because rendered_answer only grows within a section, and every breakpoint
    // trigger requires a \n to delimit the structural line, the result cannot
    // change on a chunk that contains no \n. We recompute only when the new
    // delta (chars appended since last call) contains a newline.
    // Reset to initial state at every section boundary alongside the other flags.
    var _breakpointCache = { result: null, computedAtLength: -1 };
    var answer = ''
    var rendered_answer = ''
    var response_message_id = null;
    var user_message_id = null;
    var isCancelled = false;
    // ── Diagnostic: capture raw backend text before any JS-side transforms ──
    var _rawBackendChunks = [];   // each chunk as received (pre-newline-replace)
    var _rawBackendText = '';     // accumulated raw text from backend
    
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
            if ($(e.target).closest('.delete-message-button, .delete-pair-button, .history-message-checkbox, .move-message-up-button, .move-message-down-button, .show-doubts-button, .ask-doubt-button, .open-artefacts-button, .has-doubts-btn, .copy-btn-header, .pin-message-btn, .scroll-to-bottom-btn, .header-hide-toggle, .scroll-to-top-btn, .dropdown, .dropdown-menu, .dropdown-item, [data-toggle="dropdown"]').length > 0) {
                return;
            }
            // Skip focus when multi-select is active or Cmd/Ctrl+click (toggles checkbox instead)
            if (typeof MultiSelectManager !== 'undefined' && (MultiSelectManager.count() > 0 || e.metaKey || e.ctrlKey)) return;
            
            handleMessageFocus(messageId, conversationId);
        });
        
        // Add text selection event handler
        cardElement.off('selectstart mouseup').on('selectstart mouseup', function(e) {
            // Don't trigger on button clicks, checkboxes, or dropdown elements
            if ($(e.target).closest('.delete-message-button, .delete-pair-button, .history-message-checkbox, .move-message-up-button, .move-message-down-button, .show-doubts-button, .ask-doubt-button, .open-artefacts-button, .has-doubts-btn, .copy-btn-header, .pin-message-btn, .scroll-to-bottom-btn, .header-hide-toggle, .scroll-to-top-btn, .dropdown, .dropdown-menu, .dropdown-item, [data-toggle="dropdown"]').length > 0) {
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
            if ($(e.target).closest('.delete-message-button, .delete-pair-button, .history-message-checkbox, .move-message-up-button, .move-message-down-button, .show-doubts-button, .ask-doubt-button, .open-artefacts-button, .has-doubts-btn, .copy-btn-header, .pin-message-btn, .scroll-to-bottom-btn, .header-hide-toggle, .scroll-to-top-btn, .dropdown, .dropdown-menu, .dropdown-item, [data-toggle="dropdown"]').length > 0) {
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
                    try {
                        if (card && card.find) {
                            var statusDiv = card.find('.status-div');
                            statusDiv.find('.status-text').html('Response cancelled by user');
                            statusDiv.find('.spinner-border').hide();
                            
                            // Mark streaming as ended (cancelled counts as ended)
                            card.removeAttr('data-live-stream');
                            card.attr('data-live-stream-ended', 'true');
                            
                            // Hide status after a brief moment to show the cancellation message
                            setTimeout(function() {
                                statusDiv.hide();
                            }, 2000);
                        }
                    } catch (e) { /* ignore */ }
                    
                    // [DEBUG] console.log('Stream cancelled by user');
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
            // Mark the card as actively streaming - used by ToC to decide collapsed vs expanded state
            try {
                if (card && card.attr) {
                    card.attr('data-live-stream', 'true');
                }
            } catch (e) { /* ignore */ }
            // Set up initial event handlers (without message ID initially)
            setupStreamingCardEventHandlers(card, null);
        }
        while (boundary !== -1) {
            const part = JSON.parse(buffer.slice(0, boundary));
            buffer = buffer.slice(boundary + 1);
            boundary = buffer.indexOf('\n');

            // Handle tool events (from agentic tool loop)
            if (part['type'] === 'tool_call') {
                if (typeof ToolCallManager !== 'undefined') {
                    ToolCallManager.showToolCallStatus(part['tool_id'], part['tool_name'], 'calling');
                }
                continue;
            } else if (part['type'] === 'tool_input_request') {
                // [DEBUG] console.log('[renderStreamingResponse] tool_input_request received', {conversationId: conversationId, tool_id: part['tool_id'], tool_name: part['tool_name'], ui_schema: part['ui_schema']});
                if (typeof ToolCallManager !== 'undefined') {
                    ToolCallManager.handleToolInputRequest(
                        conversationId, part['tool_id'], part['tool_name'], part['ui_schema']
                    );
                } else {
                    console.error('[renderStreamingResponse] ToolCallManager is undefined!');
                }
                continue;
            } else if (part['type'] === 'tool_status') {
                if (typeof ToolCallManager !== 'undefined') {
                    ToolCallManager.showToolCallStatus(part['tool_id'], part['tool_name'], part['tool_status'] || part['status']);
                }
                continue;
            } else if (part['type'] === 'tool_result') {
                if (typeof ToolCallManager !== 'undefined') {
                    ToolCallManager.showToolResult(part['tool_id'], part['result_summary'], part['duration_seconds']);
                }
                continue;
            }


            // ── Diagnostic: capture raw text BEFORE newline replacement ──
            var rawChunkText = part['text'] || '';
            if (rawChunkText.length > 0) {
                _rawBackendChunks.push(rawChunkText);
                _rawBackendText += rawChunkText;
            }

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
            // Perf: use cached statusDiv/spinner instead of re-querying per chunk
            if (!_cachedStatusDiv) {
                _cachedStatusDiv = card.find('.status-div');
                _cachedSpinner = _cachedStatusDiv.find('.spinner-border');
            }
            _cachedStatusDiv.show();
            _cachedSpinner.show();
            
            if (part['text'].includes('<answer>') && card.find("#message-render-space-md-render").length > 0) {
                elem_to_render = $(`<div class="answer section-${sectionCount}" id="actual-answer-rendering-space-${sectionCount}"></div>`);
                card.find("#message-render-space-md-render").append(elem_to_render);
                elem_to_render = card.find(`#actual-answer-rendering-space-${sectionCount}`).html('');
                elem_to_render = card.find(`#actual-answer-rendering-space-${sectionCount}`)
                beforeElem = elem_to_render;
                content_length = 0;
                rendered_answer = '';
                _section_already_rendered = false;
                _section_has_display_math = false;
                _breakpointCache = { result: null, computedAtLength: -1 };
                
                sectionCount++;
            }
            
            // Check for breakpoints in the current rendered text.
            // getTextAfterLastBreakpoint splits the full rendered_answer by \n and
            // scans every line — O(lines) on every chunk. Because every breakpoint
            // trigger requires a \n to exist in the text (all triggers are line-based),
            // the result cannot change on a chunk that appended no newline.
            // We cache the last result and only recompute when the new delta contains \n.
            var breakpointResult;
            var _bpDelta = rendered_answer.slice(_breakpointCache.computedAtLength);
            if (_breakpointCache.result === null || _bpDelta.includes('\n')) {
                breakpointResult = getTextAfterLastBreakpoint(rendered_answer);
                _breakpointCache = { result: breakpointResult, computedAtLength: rendered_answer.length };
            } else {
                breakpointResult = _breakpointCache.result;
            }
            
            // Don't split if the breakpoint falls inside an <answer_visual> block
            var _skipBreakpoint = false;
            if (breakpointResult.hasBreakpoint) {
                var _visOpenIdx = rendered_answer.indexOf('<answer_visual>');
                if (_visOpenIdx !== -1) {
                    var _visCloseIdx = rendered_answer.indexOf('</answer_visual>');
                    // If open exists but no close, or breakpoint is between open and close, skip
                    if (_visCloseIdx === -1 || breakpointResult.textBeforeBreakpoint.indexOf('<answer_visual>') !== -1) {
                        _skipBreakpoint = true;
                        // [DEBUG] console.warn('[STREAM] Skipping breakpoint split — inside answer_visual block');
                    }
                }
                if (!_skipBreakpoint) {
                    // [DEBUG] console.warn('[STREAM] Breakpoint WILL split | hasVisOpen:', rendered_answer.indexOf('<answer_visual>') !== -1, '| hasVisClose:', rendered_answer.indexOf('</answer_visual>') !== -1, '| beforeLen:', breakpointResult.textBeforeBreakpoint.length, '| afterLen:', breakpointResult.textAfterBreakpoint.length);
                }
            }
            if (breakpointResult.hasBreakpoint && !_skipBreakpoint) {
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
                _section_already_rendered = false;
                _section_has_display_math = false;
                _breakpointCache = { result: null, computedAtLength: -1 };
                sectionCount++;
            }
            
            // elem_to_render.append(part['text']);
            
            // ── Math-aware rendering gate ─────────────────────────────
            // 1. NEVER render while inside an unclosed display math block
            //    (\\[...  or $$... without closing delimiter). Rendering
            //    partial math triggers MathJax on incomplete expressions,
            //    causing flash-of-raw-delimiters and layout reflow.
            // 2. Use a DYNAMIC threshold: sections that already contain
            //    rendered math need fewer re-renders (each re-render forces
            //    MathJax to re-typeset everything in the section).
            //    - No math in section → 80 chars  (smooth text streaming)
            //    - Math in section    → 200 chars  (fewer MathJax re-runs)
            //
            // _section_has_display_math is set true on the first chunk that
            // introduces a math delimiter and reset at every section boundary.
            // This avoids calling isInsideDisplayMath() — which runs 5 regex
            // passes over the full accumulated string — on sections that have
            // no math at all.
            if (!_section_has_display_math) {
                _section_has_display_math = rendered_answer.includes('\\\\[')
                    || rendered_answer.includes('\\\\]')
                    || (rendered_answer.match(/\$\$/g) || []).length >= 2;
            }
            var insideMath = _section_has_display_math ? isInsideDisplayMath(rendered_answer) : false;
            var renderThreshold = _section_has_display_math ? 200 : 80;
            
            if (!insideMath
                && (rendered_answer.length > content_length + renderThreshold || breakpointResult.hasBreakpoint)) {
                // Note: the length gate already guarantees rendered_answer has grown since
                // the last render — no need for the previous rendered_till_now.includes() check.
                mathjax_elem = renderInnerContentAsMarkdown(elem_to_render,
                    callback = null, continuous = true, html = rendered_answer);
                content_length = rendered_answer.length;
                rendered_till_now = rendered_till_now + rendered_answer;
                _section_already_rendered = true;
                
            }
            
            if ((part['text'].includes('</answer>')) && card.find("#message-render-space-md-render").length > 0) {
                // _section_already_rendered is true only if the main gate above fired for this
                // exact rendered_answer value. If any new content arrived since then
                // (content_length < rendered_answer.length), we must render once more.
                var _willRerender = elem_to_render && elem_to_render.length > 0
                    && rendered_answer.length > 0
                    && (!_section_already_rendered || rendered_answer.length !== content_length);
                // [DEBUG] console.warn('[STREAM] </answer> detected | willRerender:', _willRerender, '| rendered_answer len:', rendered_answer.length, '| hasVisualOpen:', rendered_answer.indexOf('<answer_visual>') !== -1, '| hasVisualClose:', rendered_answer.indexOf('</answer_visual>') !== -1, '| elem_to_render id:', (elem_to_render && elem_to_render.attr ? elem_to_render.attr('id') : 'N/A'));
                if (_willRerender) {
                    mathjax_elem = renderInnerContentAsMarkdown(elem_to_render, 
                        immediate_callback = function() {
                            elem_to_render.attr('data-fully-rendered', 'true');
                        }, 
                        continuous = false, // Use false for final rendering to ensure proper display
                        html = rendered_answer);

                    rendered_till_now = rendered_till_now + rendered_answer;
                    _section_already_rendered = true;
                    
                }    
                elem_to_render = $(`<div class="answer section-${sectionCount}" id="actual-answer-rendering-space-${sectionCount}"></div>`);
                card.find("#message-render-space-md-render").append(elem_to_render);
                elem_to_render = card.find(`#actual-answer-rendering-space-${sectionCount}`).html('');
                elem_to_render = card.find(`#actual-answer-rendering-space-${sectionCount}`)
                beforeElem = elem_to_render;
                sectionCount++;

                content_length = 0;
                rendered_answer = '';
                _section_already_rendered = false;
                _section_has_display_math = false;
                _breakpointCache = { result: null, computedAtLength: -1 };
                
            }
            last_rendered_answer = rendered_answer;
            last_elem_to_render = elem_to_render;
            
            var statusDiv = _cachedStatusDiv || card.find('.status-div');
            statusDiv.find('.status-text').html(part['status']);

            if (part['message_ids']) {
                user_message_id = part['message_ids']['user_message_id']
                response_message_id = part['message_ids']['response_message_id']
                Array.from(card.find('.history-message-checkbox'))[0].setAttribute('message-id', response_message_id);
                Array.from(card.find('.history-message-checkbox'))[0].setAttribute('id', `message-checkbox-${response_message_id}`);
                last_card = $(card).prevAll('.card').first()
                Array.from(last_card.find('.history-message-checkbox'))[0].setAttribute('message-id', user_message_id);
                Array.from(last_card.find('.history-message-checkbox'))[0].setAttribute('id', `message-checkbox-${user_message_id}`);
                last_card.find('.has-doubts-btn').attr('message-id', user_message_id);
                
                // Update the card header with message-id attribute
                card.find('.card-header').attr('message-id', response_message_id);
                card.find('.delete-message-button').attr('message-id', response_message_id);
                card.find('.show-doubts-button').attr('message-id', response_message_id);
                card.find('.ask-doubt-button').attr('message-id', response_message_id);
                card.find('.move-message-up-button').attr('message-id', response_message_id);
                card.find('.move-message-down-button').attr('message-id', response_message_id);
                card.find('.has-doubts-btn').attr('message-id', response_message_id);
                
                // Re-setup event handlers now that we have the message ID
                setupStreamingCardEventHandlers(card, response_message_id);

                // Capture running_summary from backend so PKB memory extraction
                // can pass conversation context to the LLM without a separate API call.
                try {
                    if (part['message_ids']['running_summary'] !== undefined) {
                        ConversationManager.currentConversationSummary = part['message_ids']['running_summary'] || '';
                    }
                } catch (_e) {}

                // Update message reference badges with short hashes from streaming
                if (part['message_ids']['response_message_short_hash']) {
                    var rHash = part['message_ids']['response_message_short_hash'];
                    var rBadge = card.find('.message-ref-badge');
                    if (rBadge.length) {
                        rBadge.attr('data-msg-hash', rHash);
                        var rIdx = rBadge.data('msg-idx');
                        rBadge.text('#' + rIdx + ' \u00b7 ' + rHash);
                    }
                }
                if (part['message_ids']['user_message_short_hash']) {
                    var uHash = part['message_ids']['user_message_short_hash'];
                    var userCard = card.prev('.message-card');
                    if (!userCard.length) userCard = card.prev('.card');
                    if (userCard.length) {
                        var uBadge = userCard.find('.message-ref-badge');
                        if (uBadge.length) {
                            uBadge.attr('data-msg-hash', uHash);
                            var uIdx = uBadge.data('msg-idx');
                            uBadge.text('#' + uIdx + ' \u00b7 ' + uHash);
                        }
                    }
                }
                
                // Bootstrap 4.6 auto-initializes data-toggle="dropdown" elements on DOM
                // insertion. An explicit .dropdown() call here is redundant:
                // setupStreamingCardEventHandlers (above) re-wires all card handlers, and
                // the stream-done path initializes dropdowns via renderMessages/$newCards.
            }
        }

        if (done) {
            // ====================================================================
            // SCROLL PRESERVATION: Capture anchor ONCE here, restore ONCE after all
            // DOM work (renderInnerContentAsMarkdown + showMore + applyModelResponseTabs)
            // is complete. This is the ONLY place scroll preservation runs.
            // Inner functions do NOT do their own capture/restore to avoid drift.
            // ====================================================================
            var _streamScrollAnchor = null;
            var _streamScrollChatView = null;
            var _streamScrollTopBeforeDone = 0; // Raw scrollTop before any DOM changes
            try {
                _streamScrollChatView = $chatView(conversationId);
                if (_streamScrollChatView && _streamScrollChatView.length > 0) {
                    _streamScrollTopBeforeDone = _streamScrollChatView.scrollTop() || 0;
                    var _lastCard = _streamScrollChatView.find('.card.message-card').last();
                    _streamScrollAnchor = captureChatViewScrollAnchorForCard(_streamScrollChatView, _lastCard);
                    // console.warn('[streaming done] CAPTURED anchor:', _streamScrollAnchor ? _streamScrollAnchor.anchorId : 'null', 'scrollTop:', _streamScrollTopBeforeDone);
                }
            } catch (e) { /* ignore */ }
            
            $('#messageText').prop('working', false);
            $('#stopResponseButton').hide();
            $('#sendMessageButton').show();
            currentStreamingController = null;

            // ====================================================================
            // HEIGHT LOCK: Read offsetHeight BEFORE any DOM writes so the browser
            // does not need to force a layout flush (reflow) to produce the value.
            // Any preceding DOM write (hide, removeClass, removeAttr) would dirty
            // layout and make the read below trigger a synchronous reflow.
            // Locking minHeight here keeps the card body height constant throughout
            // all subsequent DOM changes (statusDiv teardown, tab build, showMore
            // rebuild) so scrollTop never shifts visibly.
            // Released after all synchronous DOM work + scroll restoration completes.
            // ====================================================================
            var _cardBodyForLock = null;
            var _cardBodyLockedHeight = 0;
            try {
                _cardBodyForLock = card.find('.chat-card-body')[0];
                if (_cardBodyForLock) {
                    _cardBodyLockedHeight = _cardBodyForLock.offsetHeight || 0;
                    if (_cardBodyLockedHeight > 0) {
                        _cardBodyForLock.style.minHeight = _cardBodyLockedHeight + 'px';
                    }
                }
            } catch (e) { /* ignore */ }

            // Use cached statusDiv if available; fall back to DOM query for safety
            var statusDiv = _cachedStatusDiv || card.find('.status-div');
            statusDiv.hide();
            statusDiv.find('.status-text').text('');
            var spinnerEl = _cachedSpinner || statusDiv.find('.spinner-border');
            spinnerEl.hide();
            spinnerEl.removeClass('spinner-border');
            // Clear cache — card rendering is done
            _cachedStatusDiv = null;
            _cachedSpinner = null;
            // [DEBUG] console.log('Stream complete');
            // ── Diagnostic: dump raw backend text to console ──
            // [DEBUG] console.warn('[STREAM DIAG] Raw backend text (before newline replace):', _rawBackendText);
            // [DEBUG] console.warn('[STREAM DIAG] Total chunks:', _rawBackendChunks.length, '| Total chars:', _rawBackendText.length);
            // [DEBUG] console.warn('[STREAM DIAG] First 500 chars:', _rawBackendText.substring(0, 500));
            // [DEBUG] console.warn('[STREAM DIAG] Last 500 chars:', _rawBackendText.substring(Math.max(0, _rawBackendText.length - 500)));
            // Store on window for easy console access
            window._lastStreamDiag = { rawText: _rawBackendText, chunks: _rawBackendChunks, answer: answer, rendered_answer: rendered_answer };
            // Store last 2 completed turns for PKB memory extraction context.
            // Each entry is {user, assistant} with plain text (XML tags stripped).
            try {
                if (!ConversationManager.recentTurns) {
                    ConversationManager.recentTurns = [];
                }
                // Strip XML wrapper tags the backend adds (e.g. <answer>...</answer>)
                var _plainAnswer = answer.replace(/<\/?(?:answer|thinking|status|tool_use)[^>]*>/gi, '').trim();
                ConversationManager.recentTurns.push({
                    user: (typeof messageText === 'string' ? messageText : '').trim(),
                    assistant: _plainAnswer.substring(0, 8000)  // ~2000 tokens
                });
                // Keep only last 2 turns
                if (ConversationManager.recentTurns.length > 2) {
                    ConversationManager.recentTurns.shift();
                }
            } catch (e) { /* ignore */ }
            
            // Mark streaming as ended - used by ToC to distinguish live-streaming vs post-streaming renders
            try {
                if (card && card.attr) {
                    card.removeAttr('data-live-stream');
                    card.attr('data-live-stream-ended', 'true');
                }
            } catch (e) { /* ignore */ }

            // Always render the last active section once more at the end
            // This ensures that any content less than the 150 character threshold gets rendered

            var show_more_called = {value: false};
            
            function show_more() {
                if (show_more_called.value == true) {
                    // [DEBUG] console.warn('[STREAM DONE] show_more SKIPPED (already called)');
                    return;
                }
                show_more_called.value = true;
                textElem = card.find('#message-render-space')
                // [DEBUG] console.log("Calling show_more function ...")
                // check if textElem is hidden by display: none
                
                text = card.find('#message-render-space').html()
                var _mdRenderText = card.find('#message-render-space-md-render').html() || '';
                // [DEBUG] console.warn('[STREAM DONE] show_more | #message-render-space len:', (text||'').length, '| #message-render-space-md-render len:', _mdRenderText.length, '| mdRender hasVisualDiv:', _mdRenderText.indexOf('data-answer-visual') !== -1);
                if (text.length == 0) {
                    textElem = card.find('#message-render-space-md-render');
                    text = card.find('#message-render-space-md-render').html();
                }
                // [DEBUG] console.warn('[STREAM DONE] show_more | USING textElem:', textElem.attr('id'), '| text len:', (text||'').length, '| hasVisualDiv:', (text||'').indexOf('data-answer-visual') !== -1);
                const hasSlides = (
                    (textElem && textElem.attr('data-has-slides') === 'true') ||
                    (!!card.find('.slide-presentation-wrapper').length ||
                     !!card.find('.slide-external-link').length)
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
                // _section_already_rendered reflects whether last_rendered_answer was already
                // passed to renderInnerContentAsMarkdown; O(1) flag replaces the previous
                // O(N) rendered_till_now.includes(last_rendered_answer) substring scan.
                const alreadyRendered = _section_already_rendered;
                
                // [DEBUG] console.warn('[STREAM DONE] lastRendered len:', (last_rendered_answer || '').length, '| alreadyRendered:', alreadyRendered, '| hasVisualTag:', (answer || '').indexOf('answer_visual') !== -1, '| data-live-stream:', card.attr('data-live-stream'));
                
                if (!alreadyRendered) {
                    renderInnerContentAsMarkdown(last_elem_to_render, 
                        immediate_callback=function() {
                            last_elem_to_render.attr('data-fully-rendered', 'true');
                            var _mdRender = card.find('#message-render-space-md-render');
                            // [DEBUG] console.warn('[STREAM DONE] before show_more | mdRender children:', _mdRender.children().length, '| mdRender has visual div:', _mdRender.find('[data-answer-visual]').length, '| last_elem id:', last_elem_to_render.attr('id'));
                            show_more();
                            handleMessageFocus(response_message_id, conversationId);
                        }, 
                        false, // Use false for final rendering
                        last_rendered_answer);
                    
                    rendered_till_now = rendered_till_now + last_rendered_answer;
                } else {
                    // Content was already rendered, just call show_more
                    var _mdRender = card.find('#message-render-space-md-render');
                    // [DEBUG] console.warn('[STREAM DONE] before show_more (alreadyRendered) | mdRender children:', _mdRender.children().length, '| mdRender has visual div:', _mdRender.find('[data-answer-visual]').length);
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
            // Reveal doubts button after delay (auto-takeaways may create a doubt async)
            setTimeout(function() { revealDoubtsButtons(ConversationManager.activeConversationId); }, 5000);
            // Second poll with pulse animation + toast notification for auto-doubts
            setTimeout(function() { revealDoubtsButtons(ConversationManager.activeConversationId, true); }, 25000);
            if (typeof normalizeMermaidBlocks === 'function') {
                normalizeMermaidBlocks(document);
            }
            mermaid.run({querySelector: "pre.mermaid"});
            
            // Add Top/Bottom nav controls + (non-tabbed) header hide toggle for the
            // freshly streamed message (expanded by default).
            if (card && answer.length > 300) { // Only add for longer messages
                if (typeof window.decorateMessageCardNav === 'function') {
                    window.decorateMessageCardNav(card, 'show');
                } else if (typeof window.addScrollToTopButton === 'function') {
                    window.addScrollToTopButton(card, 'Top ↑', 'chat-scroll-top');
                }
            }

            // If user navigated with a hash deep-link (e.g. from a ToC URL),
            // try to scroll to it now that the streaming message is fully rendered.
            // NOTE: Only do hash-based scroll if there's actually a hash in the URL
            var hasHashTarget = !!(window.location.hash && window.location.hash.length > 1);
            if (hasHashTarget) {
                try {
                    setTimeout(function() { scrollToHashTargetInCard(card); }, 250);
                } catch (e) { /* ignore */ }
            }
            
            // Final setup of event handlers with the complete message ID (if available)
            if (response_message_id) {
                setupStreamingCardEventHandlers(card, response_message_id);
            }
            
            // Call next question suggestions after streaming response is complete
            setTimeout(function() {
                renderNextQuestionSuggestions(conversationId);
            }, 500);
            
            // ====================================================================
            // RELEASE HEIGHT LOCK: All synchronous DOM work is complete.
            // Release min-height so the card body settles to its natural height.
            // CSS scroll anchoring (overflow-anchor: auto) will handle the small
            // height delta between the locked height and the natural height.
            // ====================================================================
            try {
                if (_cardBodyForLock && _cardBodyLockedHeight > 0) {
                    _cardBodyForLock.style.minHeight = '';
                }
            } catch (e) { /* ignore */ }
            
            // ====================================================================
            // SCROLL RESTORATION: Safety net after ALL DOM work settles.
            // With the height lock, scroll should NOT have shifted. The _tryRestore
            // checks drift and only corrects if CSS anchoring didn't handle it.
            // ====================================================================
            if (_streamScrollChatView && _streamScrollChatView.length > 0 && _streamScrollTopBeforeDone > 0) {
                // SCROLL RESTORATION STRATEGY:
                // CSS scroll anchoring (overflow-anchor: auto) automatically compensates for DOM
                // changes above the viewport. For multi-model streaming, this works perfectly.
                // Our JavaScript anchor-based restore can actually FIGHT CSS anchoring and cause
                // a ~40px drift (e.g., when TLDR tab is added to the nav bar, the tab pane
                // shifts, and our anchor computes a slightly different restore target).
                //
                // Strategy:
                // 1. If CSS scroll anchoring preserved the position (scrollTop barely changed),
                //    DON'T run JavaScript restore — it would only make things worse.
                // 2. If scrollTop drifted significantly (> 50px), use anchor-based restore.
                // 3. If anchor restore isn't available, fallback to raw scrollTop restore.
                var CSS_ANCHORING_THRESHOLD = 50; // px — if scrollTop drifted less than this, CSS anchoring handled it
                
                function _tryRestore(label) {
                    try {
                        if (!_streamScrollChatView || _streamScrollChatView.length === 0) return;
                        var currentScrollTop = _streamScrollChatView.scrollTop() || 0;
                        var drift = Math.abs(currentScrollTop - _streamScrollTopBeforeDone);
                        
                        if (drift <= CSS_ANCHORING_THRESHOLD) {
                            // CSS scroll anchoring already preserved the position — don't override.
                            // console.warn('[streaming done]', label, 'CSS OK, drift=' + Math.round(drift) + 'px');
                            return;
                        }
                        
                        // Significant drift — try anchor-based restore first
                        if (_streamScrollAnchor) {
                            restoreChatViewScrollAnchor(_streamScrollChatView, _streamScrollAnchor);
                            var afterAnchor = _streamScrollChatView.scrollTop() || 0;
                            var anchorDrift = Math.abs(afterAnchor - _streamScrollTopBeforeDone);
                            
                            // If anchor restore got us closer, keep it. Otherwise fallback to raw scrollTop.
                            if (anchorDrift < drift) {
                                // console.warn('[streaming done]', label, 'Anchor restore drift=' + Math.round(drift) + '→' + Math.round(anchorDrift));
                                return;
                            }
                        }
                        
                        // Fallback: restore raw scrollTop (clamped to valid range)
                        var maxS = (_streamScrollChatView.prop('scrollHeight') || 0) - (_streamScrollChatView.innerHeight() || 0);
                        var target = Math.max(0, Math.min(maxS, _streamScrollTopBeforeDone));
                        _streamScrollChatView.scrollTop(target);
                        // console.warn('[streaming done]', label, 'Raw scrollTop restore, drift=' + Math.round(drift));
                    } catch (e) { /* ignore */ }
                }
                
                // Immediate restore
                _tryRestore('Immediate');
                
                (function(cv, anchor, origTop, tryFn) {
                    // rAF restore
                    requestAnimationFrame(function() { tryFn('rAF'); });
                    // After show_more (500ms) + toggle + applyModelResponseTabs settle
                    setTimeout(function() { tryFn('700ms'); }, 700);
                    // Final safety net at 1200ms (after MathJax/Mermaid)
                    setTimeout(function() { tryFn('1200ms'); }, 1200);
                })(_streamScrollChatView, _streamScrollAnchor, _streamScrollTopBeforeDone, _tryRestore);
            }
            
            return;
        }
        
        // Recursive call to read next message part
        setTimeout(read, 10);
        
        } catch (error) {
            if (error.name === 'AbortError') {
                // [DEBUG] console.log('Stream was cancelled');
                // Update status for cancellation
                if (card) {
                    var statusDiv = card.find('.status-div');
                    statusDiv.find('.status-text').html('Response cancelled by user');
                    statusDiv.find('.spinner-border').hide();
                    
                    // Mark streaming as ended (cancelled counts as ended)
                    card.removeAttr('data-live-stream');
                    card.attr('data-live-stream-ended', 'true');
                    
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
                    
                    // Mark streaming as ended (error counts as ended)
                    card.removeAttr('data-live-stream');
                    card.attr('data-live-stream-ended', 'true');
                    
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
        var card = $chatView(currentStreamingController.conversationId).find('.card').last();
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
                // [DEBUG] console.log('Cancellation request sent successfully');
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
        // [DEBUG] console.log('No active doubt streaming to stop');
        return;
    }
    
    // [DEBUG] console.log('Stopping doubt clearing...');
    
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

function scrollToHashTargetInCard(cardElem) {
    /**
     * If the current URL has a hash (e.g. #m-<msg>-executive-summary),
     * attempt to expand showMore/details and scroll to that target.
     *
     * @param {jQuery} cardElem
     */
    try {
        var hash = (window.location.hash || '').replace(/^#/, '').trim();
        if (!hash) return;

        var targetEl = document.getElementById(hash);
        if (!targetEl) return;
        
        // CRITICAL: Only scroll if the hash target is actually inside this card.
        // Otherwise, a stale hash from a previous message (e.g. after clicking an older ToC link)
        // would yank the user back to a previous card when a new streaming response finishes.
        try {
            if (!cardElem || !cardElem.length || !cardElem[0] || !cardElem[0].contains(targetEl)) {
                return;
            }
        } catch (e) { return; }

        // Expand showMore if present and currently collapsed.
        var $moreText = cardElem.find('.more-text').first();
        if ($moreText.length && !$moreText.is(':visible')) {
            var $toggle = cardElem.find('.show-more').first();
            if ($toggle.length) {
                $toggle.trigger('click');
            }
        }

        // Expand <details> ancestors.
        var el = targetEl;
        while (el) {
            if (el.tagName && el.tagName.toLowerCase() === 'details') {
                el.open = true;
            }
            el = el.parentElement;
        }

        targetEl.scrollIntoView({ behavior: 'smooth', block: 'start' });
    } catch (e) {
        console.warn('scrollToHashTargetInCard failed:', e);
    }
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

/**
 * setupPaperclipAndPageDrop  —  module-level function (not a ChatManager method).
 *
 * Wires the paperclip icon click/file-input and the document-level drag-drop handler.
 * These previously lived as closures inside setupAddDocumentForm so they shared the
 * conversationId via closure.  Now they read ConversationManager.activeConversationId
 * at event time, which is always up-to-date after openConversation sets it.
 *
 * Drag-onto-page drops call /attach_doc_to_message/ (message-attach path), NOT the
 * conversation upload endpoint.  This flow is entirely unchanged from before.
 *
 * @param {string} conversationId  — passed in from setupAddDocumentForm for clarity,
 *                                   but the handlers read activeConversationId at event time.
 */
function setupPaperclipAndPageDrop(conversationId) {
    // Internal helper: upload a file as a message attachment (paperclip / page-drop).
    // Posts to /attach_doc_to_message/ so it lands in message_attached_documents_list,
    // NOT the conversation document panel.
    function uploadFileAsAttachment(file, attId) {
        var convId = ConversationManager.activeConversationId || conversationId;
        if (!DocsManagerUtils.isValidFileType(file, $('#chat-file-upload'))) {
            // [DEBUG] console.log('Invalid file type for attachment: ' + file.type);
            return;
        }
        var formData = new FormData();
        formData.append('pdf_file', file);
        var xhr = new XMLHttpRequest();
        xhr.open('POST', '/attach_doc_to_message/' + convId, true);
        xhr.onload = function () {
            if (xhr.status === 200) {
                var response = JSON.parse(xhr.responseText);
                if (attId && response.doc_id) {
                    enrichAttachmentWithDocInfo(attId, response.doc_id, response.source, response.title);
                }
            } else {
                console.error('Failed to attach document:', xhr.responseText);
            }
        };
        xhr.onerror = function () {
            console.error('Network error attaching document.');
        };
        xhr.send(formData);
    }

    // Paperclip click → hidden file input
    $('#chat-file-upload-span').off('click').on('click', function () {
        $('#chat-file-upload').click();
    });

    // Paperclip file selection
    $('#chat-file-upload').off('change').on('change', function (e) {
        var file = e.target.files[0];
        if (file) {
            var attId = addFileToAttachmentPreview(file);
            uploadFileAsAttachment(file, attId);
        }
    });

    // Document-level drag-and-drop (page drop → message attachment)
    $(document).off('dragover').on('dragover', function (event) {
        event.preventDefault();
        $(this).css('background-color', '#eee');
    });
    $(document).off('dragleave').on('dragleave', function (e) {
        $(this).css('background-color', 'transparent');
    });
    $(document).off('drop').on('drop', function (event) {
        event.preventDefault();
        $(this).css('background-color', 'transparent');
        var files = event.originalEvent.dataTransfer.files;
        for (var i = 0; i < files.length; i++) {
            var file = files[i];
            var attId = addFileToAttachmentPreview(file);
            uploadFileAsAttachment(file, attId); // message-attach path → /attach_doc_to_message/
        }
    });
}


// ---- Async chunked rendering: cancellation token ----
// Incremented each time a chunked render starts. Each chunk checks this
// before flushing; if it changed (user switched conversations, or streaming
// started), the stale render is silently abandoned.
var _renderGeneration = 0;

// ---- R2: Render-complete signalling for fetch-early / apply-late ----
// Resolved by _runPostRenderWork after ALL cards are in the live DOM.
// Allows pre-fired network fetches (doubts, pins) to defer their DOM
// manipulation until cards actually exist — fixing the existing race where
// async chunked rendering hadn't finished when fetch responses arrived.
var _renderCompleteResolve = null;
var _renderCompletePromise = null;

function _resetRenderCompletePromise() {
    _renderCompletePromise = new Promise(function (resolve) {
        _renderCompleteResolve = resolve;
    });
}
_resetRenderCompletePromise();  // initialise

var ChatManager = {
    shownDoc: null,
    listMessages: function (conversationId, includeUiState) {
        var url = '/list_messages_by_conversation/' + conversationId;
        if (includeUiState) {
            // Fold section-collapse state into the response so the load flow reaches
            // final rendered state in ONE round trip (and one server-side conversation
            // load). Per-message show_hide already ships in each message object.
            url += '?include_ui_state=true';
        }
        return $.ajax({
            url: url,
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
                    var $cv = $chatView();
                    $cv.animate({ scrollTop: $cv.prop("scrollHeight") }, "fast");
                    // REMOVED: Auto-focus on messageText causes soft keyboard on mobile/tablet.
                    // $('#messageText').focus();

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
                LocalDocsManager.refresh(conversationId);
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
        // Delegate local-doc modal wiring to LocalDocsManager.
        LocalDocsManager.setup(conversationId);
        // Paperclip and page-drop handlers (message attachment flow — unchanged).
        setupPaperclipAndPageDrop(conversationId);
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
    deleteMessagePair: function (conversationId, messageId, index) {
        return $.ajax({
            url: '/delete_message_pair/' + conversationId + '/' + messageId + '/' + index,
            type: 'DELETE'
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
                // [DEBUG] console.log(response);
            },
            error: function (response) {
                alert('Refresh page, move messages error, Error: ' + response.responseText);
            }
        });
    },
    renderMessages: function (conversationId, messages, shouldClearChatView, initialize_voting = true, history_message_ids = [], skip_one = false) {
        var _renderMsgsT = _perfStart('renderMessages');
        // Reset per-card details for this render pass
        if (window._PERF) { window._perfCardDetails = []; }
        // R2: Reset the render-complete promise so pre-fired fetches (doubts/pins)
        // wait for THIS render pass to finish before applying DOM changes.
        _resetRenderCompletePromise();

        if (shouldClearChatView) {
            $chatView(conversationId).empty();  // Clear the chat view first
            cleanupMessageObservers();
        }
        // Clear the "already applied" flag so the synchronous per-card apply in
        // renderInnerContentAsMarkdown re-runs and the debounced fetchConversationUIState
        // is not incorrectly skipped on this fresh render pass.
        try {
            if (window.ConversationUIState && typeof window.ConversationUIState.clearApplied === 'function') {
                window.ConversationUIState.clearApplied(conversationId);
            }
        } catch (_e) { /* ignore */ }
        
        var messageElement = null;

        // Snapshot the existing card count ONCE before the loop (H6 fix).
        var initialCardCount = $chatView(conversationId).find('.message-card').length;

        // Collect newly created card elements so Bootstrap dropdown init can be
        // scoped to just these cards (Fix: dropdown outside-click bug).
        var newMessageElements = [];

        // Perf: hoist constant settings read outside the loop — the checkbox
        // value doesn't change mid-render, so reading it once saves N-1 DOM queries.
        var renderCloseToSource = $('#settings-render-close-to-source').is(':checked');

        // Perf: reusable container for native innerHTML parsing of card headers.
        // Avoids jQuery's $() per-card overhead (creates temp div, innerHTML,
        // extracts children, wraps in jQuery).  We reuse a single detached div
        // and extract firstElementChild after each innerHTML assignment.
        var _headerParser = document.createElement('div');

        // ---- Helper: build a single message card (pure DOM, no live-DOM insertion) ----
        // Returns the jQuery-wrapped card element.  Side-effects: pushes onto
        // newMessageElements, calls initialiseVoteBank, renderInnerContentAsMarkdown.
        function _buildMessageCard(message, originalIndex, totalCount) {
            var _perfT = _perfStart('buildCard#' + originalIndex);
            var _tmplT = _perfStart('cardTemplate#' + originalIndex);
            var index = initialCardCount + originalIndex;
            var isLastInBatch = (originalIndex === totalCount - 1);
            var senderText = message.sender === 'user' ? 'You' : 'Assistant';
            var showHide = message.show_hide || 'hide';
            var userHidden = message.user_hidden === true;

            // Per-card perf detail record — sub-steps write their timings into this.
            var _cardDetail = {
                index: originalIndex,
                sender: message.sender || 'unknown',
                showHide: showHide,
                textLen: message.text ? message.text.length : 0,
                willCollapse: (showHide !== 'show' && (message.text ? message.text.length : 0) > 300),
                userHidden: userHidden,
                buildCard_ms: 0,
                renderInner_ms: 0,
                showMore_ms: 0,
                decorateNav_ms: 0
            };
            if (window._PERF) {
                window._perfCardDetails = window._perfCardDetails || [];
                window._perfCardDetails.push(_cardDetail);
            }
            var cardElem = $('<div class="mb-1 mt-0 card w-100 my-1 d-flex flex-column message-card"></div>');
            newMessageElements.push(cardElem);
            if (userHidden) cardElem.css('display', 'none').addClass('message-user-hidden');
            // Create action dropdown for left side (doubts, delete, move)
            var actionDropdown = `
                <div class="dropdown d-inline-block message-action-dropdown">
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
                        <a class="dropdown-item open-artefacts-button" href="#" message-index="${index}" message-id="${message.message_id}">
                            <i class="bi bi-files mr-2"></i>Artefacts
                        </a>
                        <a class="dropdown-item fork-from-here-button" href="#" message-index="${index}">
                            <i class="bi bi-signpost-split mr-2"></i>Fork from here
                        </a>
                        <div class="dropdown-divider"></div>
                        <a class="dropdown-item delete-message-button text-danger" href="#" message-index="${index}" message-id="${message.message_id}">
                            <i class="bi bi-trash-fill mr-2"></i>Delete Message
                        </a>
                        <a class="dropdown-item delete-pair-button text-danger" href="#" message-index="${index}" message-id="${message.message_id}" message-sender="${message.sender}">
                            <i class="bi bi-trash mr-2"></i>Delete Pair
                        </a>
                        <a class="dropdown-item move-pair-as-doubt-button text-warning" href="#"
                            message-index="${index}" message-id="${message.message_id}" message-sender="${message.sender}"
                            style="${(message.sender === 'user' ? index < 1 : index < 2) ? 'display:none;' : ''}">
                            <i class="bi bi-arrow-up-right-circle mr-2"></i>Move Pair as Doubt
                        </a>
                    </div>
                </div>`;
            
            var displayIndex = originalIndex + 1;
            var msgHash = message.message_short_hash || '';
            var refBadgeText = '#' + displayIndex + (msgHash ? ' \u00b7 ' + msgHash : '');
            var cardHeaderHTML = `<div class="card-header d-flex justify-content-between align-items-center" message-index="${index}" message-id=${message.message_id}>
                <div class="d-flex align-items-center">
                    <input type="checkbox" class="history-message-checkbox mr-2" id="message-checkbox-${message.message_id}" message-id=${message.message_id}>
                    <small><small><strong>` + senderText + `</strong><span class="message-ref-badge text-muted" style="font-family:monospace;font-size:0.65rem;cursor:pointer;margin-left:4px;" data-msg-idx="${displayIndex}" data-msg-hash="${msgHash}" title="Click to copy message reference">${refBadgeText}</span></small></small>
                    ${actionDropdown}
                    <button class="btn btn-sm p-1 has-doubts-btn" title="Show Doubts" message-id="${message.message_id}" style="display:none;"><i class="bi bi-chat-left-text"></i></button>
                </div>
                <div class="d-flex align-items-center">
                    <button class="btn btn-sm p-1 scroll-to-bottom-btn chat-scroll-bottom" title="Jump to the bottom of this message" style="display:none;">Bottom <i class="bi bi-arrow-down-short"></i></button>
                    <a href="#" class="header-hide-toggle" title="Collapse / expand this answer" style="display:none;">[hide]</a>
                    <button class="btn btn-sm p-1 copy-btn-header" title="Copy Text">
                        <i class="bi bi-clipboard"></i>
                    </button>
                    <button class="btn btn-sm p-1 pin-message-btn" title="Pin/Unpin Message" data-message-id="${message.message_id || ''}" style="${message.sender === 'user' ? 'display:none;' : ''}">
                        <i class="bi bi-star"></i>
                    </button>
                    <div class="dropdown d-inline-block vote-menu-dropdown-container">
                        <button class="btn btn-sm p-1 dropdown-toggle-no-caret vote-menu-toggle" type="button" data-toggle="dropdown" aria-haspopup="true" aria-expanded="false" title="More Options">
                            <i class="bi bi-three-dots-vertical"></i>
                        </button>
                        <div class="dropdown-menu dropdown-menu-right vote-dropdown-menu">
                            <!-- Vote buttons will be inserted here by initialiseVoteBank -->
                        </div>
                    </div>
                    <div class="dropdown compact-message-menu-container">
                        <button class="btn btn-sm p-1 dropdown-toggle-no-caret compact-message-menu-toggle" type="button" data-toggle="dropdown" aria-haspopup="true" aria-expanded="false" title="Options">
                            <i class="bi bi-three-dots-vertical"></i>
                        </button>
                        <div class="dropdown-menu dropdown-menu-right compact-message-dropdown-menu">
                            <span class="dropdown-item-text text-muted compact-word-count" style="font-size:0.7rem;padding:2px 12px;"></span>
                            <div class="dropdown-divider compact-word-count-divider"></div>
                            <a class="dropdown-item compact-proxy-edit-message" href="#"><i class="bi bi-pencil mr-2"></i>Edit Message</a>
                            <div class="dropdown-divider"></div>
                            <a class="dropdown-item compact-proxy-bottom" href="#"><i class="bi bi-arrow-down-short mr-2"></i>Bottom</a>
                            <a class="dropdown-item compact-proxy-show-hide" href="#"></a>
                            <a class="dropdown-item compact-proxy-copy" href="#"><i class="bi bi-clipboard mr-2"></i>Copy</a>
                            <div class="dropdown-divider"></div>
                            <a class="dropdown-item compact-proxy-show-doubts" href="#"><i class="bi bi-question-circle mr-2"></i>Show Doubts</a>
                            <a class="dropdown-item compact-proxy-ask-doubt" href="#"><i class="bi bi-plus-circle mr-2"></i>Ask New Doubt</a>
                            <div class="dropdown-divider"></div>
                            <a class="dropdown-item compact-proxy-fork" href="#"><i class="bi bi-signpost-split mr-2"></i>Fork from here</a>
                            <div class="dropdown-divider"></div>
                            <a class="dropdown-item text-danger compact-proxy-delete-message" href="#"><i class="bi bi-trash-fill mr-2"></i>Delete Message</a>
                            <a class="dropdown-item text-danger compact-proxy-delete-pair" href="#"><i class="bi bi-trash mr-2"></i>Delete Pair</a>
                            <a class="dropdown-item text-warning compact-proxy-move-pair" href="#"><i class="bi bi-arrow-up-right-circle mr-2"></i>Move Pair as Doubt</a>
                            <div class="dropdown-divider compact-read-divider"></div>
                            <a class="dropdown-item compact-proxy-read" href="#"><i class="bi bi-arrows-fullscreen mr-2"></i>Read Full Screen</a>
                        </div>
                    </div>
                </div>
            </div>`;
            // Parse via reusable native container — avoids jQuery $() overhead
            // which creates a temp div, innerHTML, extracts children, wraps.
            _headerParser.innerHTML = cardHeaderHTML;
            var cardHeader = _headerParser.firstElementChild;
            var _templateDone = _perfEnd('cardTemplate#' + originalIndex, _tmplT);
            var cardBody = $('<div class="card-body chat-card-body" style="font-size: 0.8rem;"></div>');
            var textElem = $('<div id="message-render-space" class="card-text actual-card-text"></div>');
            // Note: we intentionally skip textElem.html(message.text) here — the content
            // is set by renderInnerContentAsMarkdown below (which overwrites innerHTML).
            // For empty messages, textElem stays empty (correct). Saves one .html() parse
            // per card on history load.

            cardBody.append(textElem);
            
            if (message.display_attachments && message.display_attachments.length > 0) {
                renderDisplayAttachmentBadges(message.display_attachments, cardBody, conversationId);
            }
            
            cardElem.append(cardHeader);
            cardElem.append(cardBody);

            // Depending on who the sender is, we adjust the alignment and add different background shading
            
            if (message.sender == 'user') {
                cardElem.css('background-color', '#fdfdfd');
                if (message.text.trim().length > 0) {
                    msgElements = [$(cardElem)];
                    // Defer vote bank setup — user won't interact with dropdown menus
                    // before reading the content.  setTimeout(0) runs after the chunk
                    // yields and the browser paints the card.
                    (function(_ce, _mt, _mid, _adid) {
                        setTimeout(function() {
                            var _vbT = _perfStart('deferredVoteBank');
                            initialiseVoteBank(_ce, _mt, contentId = _mid, activeDocId = _adid, disable_voting = true);
                            _perfEnd('deferredVoteBank', _vbT);
                        }, 0);
                    })(cardElem, message.text, message.message_id, ConversationManager.activeConversationId);
                }
            } else {
                if (message.text.trim().length > 0) {
                    msgElements = [$(cardElem)];
                    (function(_ce, _mt, _mid, _adid, _iv) {
                        setTimeout(function() {
                            var _vbT = _perfStart('deferredVoteBank');
                            initialiseVoteBank(_ce, _mt, contentId = _mid, activeDocId = _adid, disable_voting = !_iv);
                            _perfEnd('deferredVoteBank', _vbT);
                        }, 0);
                    })(cardElem, message.text, message.message_id, ConversationManager.activeConversationId, initialize_voting);
                }
                cardElem.css('background-color', '#ffffff');
            }
            
            if (message.text.trim().length > 0) {
                (function(currentMessageElement, currentMessage, currentTextElem, currentShowHide, isLastMessage, _cd) {
                    // When the card will be collapsed by showMore() (show_hide != 'show'
                    // and text long enough), skip applyModelResponseTabs, ToC, and UI state
                    // restore inside renderInnerContentAsMarkdown — they're invisible behind
                    // [show] and the delegated expand handler re-applies them on first click.
                    // This saves 50-200ms of DOM work per collapsed card.
                    var _willCollapse = (currentShowHide !== 'show' && currentMessage.text.length > 300);
                    var _rimStart = performance.now();
                    renderInnerContentAsMarkdown(currentTextElem,
                        /* callback (runs after MathJax) */ null,
                        /* continuous */ false,
                        /* html */ currentMessage.text.replace(/\n/g, '  \n'),
                        /* immediate_callback (runs synchronously) */ function () {
                            var _textElem = currentTextElem;
                            var _showHide = currentShowHide;
                            var _currentMessage = currentMessage;
                            var _currentMessageElement = currentMessageElement;
                            
                            // Slide detection: check cheap attribute + string gate FIRST.
                            // The jQuery .find() calls are expensive (full subtree scan) and
                            // slides are extremely rare (~0-1 cards out of 111).  Gate on
                            // the raw message text to avoid DOM traversal for 99%+ of cards.
                            var hasSlides = (
                                (_textElem && _textElem.attr('data-has-slides') === 'true') ||
                                (_currentMessage.text.indexOf('slide-presentation') !== -1 && (
                                    !!_textElem.closest('.card-body').find('.slide-presentation-wrapper').length ||
                                    !!_textElem.closest('.card-body').find('.slide-external-link').length
                                ))
                            );
                            if (hasSlides) {
                                setTimeout(function() {
                                    var slideWrapper = _textElem.closest('.card-body').find('.slide-presentation-wrapper');
                                    if (slideWrapper.length > 0) {
                                        adjustCardHeightForSlides(slideWrapper);
                                    }
                                }, 100);
                            } else if (_currentMessage.text.length > 300) {
                                var _smStart = performance.now();
                                showMore(null, text = null, textElem = _textElem, as_html = true, show_at_start = _showHide === 'show', server_side = {
                                    'message_id': _currentMessage.message_id
                                });
                                _cd.showMore_ms = performance.now() - _smStart;
                            }
                            
                            if (_currentMessage.text.length > 300) {
                                // Defer navigation button setup — cosmetic aids that don't
                                // affect content visibility (scroll-to-bottom, scroll-to-top,
                                // header collapse sync, ToC visibility).
                                // R-H5a: Skip for collapsed cards — content is hidden behind
                                // [show] link, so nav buttons are invisible. The delegated
                                // expand handler calls decorateMessageCardNav on first expand.
                                if (_showHide === 'show' && typeof window.decorateMessageCardNav === 'function') {
                                    setTimeout(function() {
                                        var _dnT = _perfStart('deferredDecorateNav');
                                        window.decorateMessageCardNav(_currentMessageElement, _showHide);
                                        _cd.decorateNav_ms = _perfEnd('deferredDecorateNav', _dnT) || 0;
                                    }, 0);
                                }
                            }
                        },
                        /* defer_mathjax */ !isLastMessage,
                        /* skip_deferred_formatting */ _willCollapse
                    );
                    _cd.renderInner_ms = performance.now() - _rimStart;
                })(cardElem, message, textElem, showHide, isLastInBatch, _cardDetail);
            }

            var statusDiv = $('<div class="status-div d-flex align-items-center"></div>');
            var spinner = $('<div class="spinner-border text-primary" role="status"></div>');
            var statusText = $('<span class="status-text ml-2"></span>');

            statusDiv.append(spinner);
            statusDiv.append(statusText);
            cardElem.append(statusDiv);
            statusDiv.hide();
            statusDiv.find('.spinner-border').hide();

            _cardDetail.buildCard_ms = _perfEnd('buildCard#' + originalIndex, _perfT) || 0;
            return cardElem;
        }

        // ---- Helper: post-render work (mermaid, dropdowns, URL scroll, etc.) ----
        // Called once after ALL cards are in the live DOM — either immediately
        // (synchronous path) or after the last chunk flushes (async path).
        function _runPostRenderWork() {
            var _prwT = _perfStart('postRenderWork');
            setTimeout(function() {
                var _mermT = _perfStart('mermaidRun');
                if (typeof normalizeMermaidBlocks === 'function') {
                    normalizeMermaidBlocks(document);
                }
                mermaid.run({querySelector: "pre.mermaid"});
                _perfEnd('mermaidRun', _mermT);
            }, 100);

            // Initialize Bootstrap 4.6 dropdowns — scoped to newly rendered cards only.
            setTimeout(function() {
                var _ddT = _perfStart('dropdownInit');
                var $newCards = $(newMessageElements);
                $newCards.find('[data-toggle="dropdown"]').dropdown();
                _perfEnd('dropdownInit', _ddT);
            }, 50);
            
            // Check if URL contains a message ID and scroll to that message
            var messageIdFromUrl = getMessageIdFromUrl();
            if (messageIdFromUrl && shouldClearChatView) {
                setTimeout(function() {
                    var targetMessageElement = $('[message-id="' + messageIdFromUrl + '"]');
                    var targetMessageCard = targetMessageElement.length > 0 ? targetMessageElement.closest('.card') : $();
                    if (targetMessageCard && targetMessageCard.length > 0) {
                        targetMessageCard.addClass('highlight-message');
                        setTimeout(function() {
                            targetMessageCard.removeClass('highlight-message');
                        }, 2000);
                    }
                }, 100);
            }

            // If the URL also contains a hash target (ToC deep link), try to scroll to it after render.
            if (shouldClearChatView) {
                setTimeout(function() {
                    try {
                        var hash = (window.location.hash || '').trim();
                        if (!hash) return;
                        var $targetCard = $('[message-id="' + messageIdFromUrl + '"]').closest('.card');
                        if ($targetCard && $targetCard.length > 0) {
                            scrollToHashTargetInCard($targetCard);
                        }
                    } catch (e) { /* ignore */ }
                }, 250);
            }
            
            // Call next question suggestions after rendering messages
            if (shouldClearChatView) {
                setTimeout(function() {
                    renderNextQuestionSuggestions(conversationId);
                }, 200);
            }

            // After rendering, schedule a debounced DOM snapshot save for fast resume.
            try {
                if (window.RenderedStateManager && window.RenderedStateManager.scheduleSave) {
                    window.RenderedStateManager.scheduleSave(conversationId);
                }
            } catch (_e) { /* ignore */ }

            // Item 3.3: hide the page loader now that cards are in the DOM.
            // This replaces the old blind 1s setTimeout in chat_interface_readiness().
            try { $("#loader").hide(); } catch (_e) { /* ignore */ }

            _perfEnd('postRenderWork', _prwT);

            // R2: Signal that all cards are in the live DOM. Pre-fired network
            // fetches (doubts, pins) wait on this before applying DOM changes.
            if (typeof _renderCompleteResolve === 'function') {
                _renderCompleteResolve();
            }

            _perfEnd('renderMessages', _renderMsgsT);
            // Mark when deferred work (voteBank, decorateNav, doubts, pins) all completes.
            // Use a longer timeout since these are setTimeout(0) deferred items.
            if (window._PERF) {
                setTimeout(function() {
                    _perfEnd('fullyInteractive', window._perfFullyInteractiveStart || 0);
                    _perfSummary();
                }, 500);
            }
        }

        // ================================================================
        // HYBRID TWO-PHASE RENDERING PATH
        // ================================================================
        // When loading a full conversation (shouldClearChatView=true) with many
        // messages, we use a two-phase hybrid approach:
        //
        // Phase 1: Build and insert the first IMMEDIATE_COUNT (4) cards into the
        //   live DOM synchronously.  The user sees readable content in <250ms.
        //
        // Phase 2: Yield once (setTimeout(0)) so the browser paints those 4 cards.
        //   Then build ALL remaining cards off-DOM in a DocumentFragment — this is
        //   pure JS work with zero layout passes since the fragment is detached.
        //   Finally, append the fragment in a single shot → one layout pass.
        //
        // This replaces the previous multi-chunk approach (7 yields × 625ms layout
        // gap each = 4.4s wasted on inter-chunk layout).  The hybrid path eliminates
        // all inter-chunk gaps, paying only one ~600ms layout pass at the end.
        //
        // With content-visibility: auto on .message-card, even that final layout
        // pass is cheap — the browser skips layout for off-screen cards.
        //
        // The synchronous path is preserved unchanged for:
        // - Small batches (<=IMMEDIATE_COUNT messages)
        // - Incremental appends (shouldClearChatView=false) — streaming, sendMessage
        // - renderCloseToSource positional inserts — need live-DOM per card
        var IMMEDIATE_COUNT = 4;
        var usePositionalInsert = (renderCloseToSource && history_message_ids.length > 0);
        var useChunkedPath = (shouldClearChatView && messages.length > IMMEDIATE_COUNT && !usePositionalInsert);

        if (useChunkedPath) {
            // ---- Hybrid two-phase path ----
            var renderToken = ++_renderGeneration;
            var chatViewEl = $chatView(conversationId)[0];
            var totalCount = messages.length;

            messageElement = null;  // will be set during card processing

            // Phase 1: Build and insert first IMMEDIATE_COUNT cards synchronously
            var _phase1T = _perfStart('renderPhase1_immediate');
            var firstFragment = document.createDocumentFragment();
            for (var i = 0; i < IMMEDIATE_COUNT && i < totalCount; i++) {
                var card = _buildMessageCard(messages[i], i, totalCount);
                firstFragment.appendChild(card[0]);
                messageElement = card;
            }
            chatViewEl.appendChild(firstFragment);
            _perfEnd('renderPhase1_immediate', _phase1T);

            // Phase 2: Yield once to paint the first cards, then build the rest off-DOM
            setTimeout(function() {
                if (_renderGeneration !== renderToken) return;

                var _phase2T = _perfStart('renderPhase2_offDOM');
                var bulkFragment = document.createDocumentFragment();
                for (var j = IMMEDIATE_COUNT; j < totalCount; j++) {
                    if (_renderGeneration !== renderToken) return;  // cancellation check
                    var card = _buildMessageCard(messages[j], j, totalCount);
                    bulkFragment.appendChild(card[0]);
                    messageElement = card;
                }
                _perfEnd('renderPhase2_offDOM', _phase2T);

                // Phase 3: Single DOM append — one layout pass
                var _appendT = _perfStart('renderPhase3_append');
                chatViewEl.appendChild(bulkFragment);
                _perfEnd('renderPhase3_append', _appendT);

                // All cards are in DOM — run post-render work
                _runPostRenderWork();
            }, 0);

            return messageElement;
        }

        // ================================================================
        // SYNCHRONOUS PATH (small batches, incremental appends, positional inserts)
        // ================================================================
        // ---- Item 8: DocumentFragment batching ----
        var useFragment = !usePositionalInsert;
        var fragment = useFragment ? document.createDocumentFragment() : null;
        // Item 2.2: O(1) Set lookup instead of O(M) Array.includes for history IDs
        var historyIdSet = usePositionalInsert ? new Set(history_message_ids) : null;

        messages.forEach(function (message, originalIndex, array) {
            var card = _buildMessageCard(message, originalIndex, array.length);
            messageElement = card;

            if (usePositionalInsert) {
                // renderCloseToSource path: positional insert after history cards
                // Re-query is intentional — each insert changes the live DOM order.
                var cards = $chatView(conversationId).find('.card.message-card');
                var lastCard = null;
                for (var ci = 0; ci < cards.length; ci++) {
                    var cardMessageId = $(cards[ci]).find('.history-message-checkbox').attr('message-id');
                    if (historyIdSet.has(cardMessageId)) {
                        lastCard = cards[ci];
                    }
                }
                if (lastCard) {
                    if (skip_one) {
                        $(lastCard).next().after(card);
                    } else {
                        $(lastCard).after(card);
                    }
                } else {
                    $chatView(conversationId).append(card);
                }
            } else {
                // Item 8: collect into off-DOM fragment (appended after loop)
                fragment.appendChild(card[0]);
            }
        });

        // ---- Item 8: flush the DocumentFragment into the live DOM ----
        if (fragment && fragment.childNodes.length > 0) {
            $chatView(conversationId)[0].appendChild(fragment);
        }

        // Post-render work runs immediately for synchronous path
        _runPostRenderWork();
        
        return messageElement;
    },




    sendMessage: function (conversationId, messageText, checkboxes, links, search, attached_claim_ids, referenced_claim_ids, referenced_friendly_ids) {
        // Render user's message immediately (include display_attachments for inline preview)
        var displayAtts = getDisplayAttachmentsPayload();
        var userMessage = {
            sender: 'user',
            text: messageText,
            display_attachments: displayAtts
        };
        history_message_ids = checkboxes['history_message_ids'] || []

        ChatManager.renderMessages(conversationId, [userMessage], false, true, history_message_ids, false);

        // Build request body
        var requestBody = {
            'messageText': messageText,
            'checkboxes': checkboxes,
            'links': links,
            'search': search
        };
        
        if (displayAtts) {
            requestBody['display_attachments'] = displayAtts;
        }
        
        // Include attached claim IDs if provided (Deliberate Memory Attachment)
        if (attached_claim_ids && attached_claim_ids.length > 0) {
            requestBody['attached_claim_ids'] = attached_claim_ids;
        }
        
        // Include referenced claim IDs from @memory: refs if provided
        if (referenced_claim_ids && referenced_claim_ids.length > 0) {
            requestBody['referenced_claim_ids'] = referenced_claim_ids;
        }
        
        // Include referenced friendly IDs from @friendly_id refs if provided (v0.5)
        if (referenced_friendly_ids && referenced_friendly_ids.length > 0) {
            requestBody['referenced_friendly_ids'] = referenced_friendly_ids;
        }

        if (typeof PageContextManager !== 'undefined' && PageContextManager.hasContext()) {
            requestBody['page_context'] = PageContextManager.getPageContextForPayload();
        }

        if (typeof WorkflowManager !== 'undefined') {
            var workflowId = WorkflowManager.getSelectedWorkflowId();
            if (workflowId) {
                requestBody['checkboxes'] = requestBody['checkboxes'] || {};
                requestBody['checkboxes']['workflow_id'] = workflowId;
                requestBody['checkboxes']['field'] = 'PromptWorkflowAgent';
            }
        }

        clearAttachmentPreviews();

        // Use Fetch API to make request
        let response = fetch('/send_message/' + conversationId, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(requestBody)
        });
        responseWaitAndSuccessChecker('/send_message/' + conversationId, response);
        return response;
    },

    _pinnedMessageIds: new Set(),

    _fetchAndHighlightPins: function (conversationId) {
        var self = this;
        self._pinnedMessageIds.clear();
        $.get('/get_pinned_messages/' + conversationId, function (data) {
            if (data && data.pinned_messages) {
                data.pinned_messages.forEach(function (p) { self._pinnedMessageIds.add(p.message_id); });
                self._applyPinsToCards();
            }
        });
    },

    // R2: Fetch-only — returns a jQuery Deferred resolving with pinned_messages
    // array (or empty array on failure). Populates _pinnedMessageIds as a side
    // effect so the Set is available for other code paths (e.g. pin toggle).
    _fetchPinsData: function (conversationId) {
        var self = this;
        var deferred = $.Deferred();
        self._pinnedMessageIds.clear();
        $.get('/get_pinned_messages/' + conversationId, function (data) {
            if (data && data.pinned_messages) {
                data.pinned_messages.forEach(function (p) { self._pinnedMessageIds.add(p.message_id); });
                deferred.resolve(data.pinned_messages);
            } else {
                deferred.resolve([]);
            }
        }).fail(function () { deferred.resolve([]); });
        return deferred.promise();
    },

    // R2: Apply-only — highlights star icons on pinned message cards.
    // Reads from _pinnedMessageIds (must be populated first via _fetchPinsData).
    _applyPinsToCards: function () {
        var self = this;
        if (self._pinnedMessageIds.size === 0) return;
        $chatView().find('.pin-message-btn').each(function () {
            var msgId = $(this).data('message-id');
            if (self._pinnedMessageIds.has(String(msgId))) {
                $(this).find('i').removeClass('bi-star').addClass('bi-star-fill text-warning');
            }
        });
    }

};

// Delegated pin/unpin click handler
$(document).on('click', '.pin-message-btn', function (e) {
    e.preventDefault();
    e.stopPropagation();
    var btn = $(this);
    var msgId = String(btn.data('message-id'));
    var convId = ConversationManager.activeConversationId;
    if (!convId || !msgId) return;
    $.post('/pin_message/' + convId + '/' + msgId, function (data) {
        if (data && data.success) {
            var icon = btn.find('i');
            if (data.pinned) {
                icon.removeClass('bi-star').addClass('bi-star-fill text-warning');
                ChatManager._pinnedMessageIds.add(msgId);
            } else {
                icon.removeClass('bi-star-fill text-warning').addClass('bi-star');
                ChatManager._pinnedMessageIds.delete(msgId);
            }
        }
    });
});

// Starred messages modal
$(document).on('click', '#starred-messages-btn', function () {
    var convId = ConversationManager.activeConversationId;
    if (!convId) { if (typeof showToast === 'function') showToast('No active conversation', 'warning'); return; }
    var body = $('#starred-messages-body');
    body.html('<p class="text-muted">Loading...</p>');
    $('#starred-messages-modal').modal('show');
    $.get('/get_pinned_messages/' + convId, function (data) {
        if (!data || !data.pinned_messages || data.pinned_messages.length === 0) {
            body.html('<p class="text-muted">No starred messages yet. Click the <i class="bi bi-star"></i> icon on any assistant message to star it.</p>');
            return;
        }
        var html = '';
        data.pinned_messages.forEach(function (pin) {
            var preview = $('<span>').text(pin.preview || '(no preview)').html();
            html += '<div class="starred-msg-item mb-2 p-2 border rounded">' +
                '<div class="starred-msg-preview" style="font-size:0.82rem;">' + preview + '</div>' +
                '<div class="mt-1">' +
                '<a href="#" class="starred-msg-goto small" data-message-id="' + pin.message_id + '">Go to message</a> &middot; ' +
                '<a href="#" class="starred-msg-view small" data-message-id="' + pin.message_id + '">View full</a>' +
                '</div></div>';
        });
        body.html(html);
    });
});

// Go to starred message
$(document).on('click', '.starred-msg-goto', function (e) {
    e.preventDefault();
    var msgId = $(this).data('message-id');
    $('#starred-messages-modal').modal('hide');
    var target = $chatView().find('.card-header[message-id="' + msgId + '"]');
    if (target.length) {
        target[0].scrollIntoView({ behavior: 'smooth', block: 'center' });
        target.closest('.message-card').addClass('highlight-flash');
        setTimeout(function () { target.closest('.message-card').removeClass('highlight-flash'); }, 2000);
    }
});

// View full starred message via markdown viewer
$(document).on('click', '.starred-msg-view', function (e) {
    e.preventDefault();
    var msgId = $(this).data('message-id');
    var card = $chatView().find('.card-header[message-id="' + msgId + '"]').closest('.message-card');
    if (card.length) {
        var content = card.find('.actual-card-text').html();
        var viewer = $('#starred-messages-body');
        viewer.html('<div class="mb-2"><a href="#" class="starred-msg-back small">&laquo; Back to list</a></div><div class="starred-msg-full-content" style="font-size:0.85rem;">' + content + '</div>');
    }
});

// Back to starred list
$(document).on('click', '.starred-msg-back', function (e) {
    e.preventDefault();
    $('#starred-messages-btn').trigger('click');
});

// --- Auto-Archive Settings ---
$(document).on('shown.bs.modal', '#chat-settings-modal', function () {
    $.get('/get_auto_archive_setting', function (data) {
        $('#auto-archive-grace-select').val(String(data.auto_archive_grace_days || 90));
    });
});

$(document).on('change', '#auto-archive-grace-select', function () {
    var val = parseInt($(this).val(), 10);
    $.ajax({ url: '/set_auto_archive_setting', type: 'POST', contentType: 'application/json', data: JSON.stringify({ auto_archive_grace_days: val }) });
});

$(document).on('click', '#mass-archive-btn', function () {
    if (!confirm('This will archive all stale conversations based on your grace period setting. Proceed?')) return;
    var domain = (typeof currentDomain !== 'undefined' && currentDomain) ? currentDomain['domain'] : 'assistant';
    var btn = $(this);
    btn.prop('disabled', true).text('Archiving...');
    $.ajax({
        url: '/auto_archive_all/' + domain,
        type: 'POST',
        success: function (data) {
            btn.prop('disabled', false).html('<i class="fa fa-archive"></i> Archive Stale Conversations');
            var count = data.count || 0;
            if (typeof showToast === 'function') {
                showToast(count + ' conversation' + (count !== 1 ? 's' : '') + ' archived', count > 0 ? 'success' : 'info');
            }
            if (count > 0 && typeof WorkspaceManager !== 'undefined') {
                WorkspaceManager.loadConversationsWithWorkspaces(false);
            }
        },
        error: function () {
            btn.prop('disabled', false).html('<i class="fa fa-archive"></i> Archive Stale Conversations');
            if (typeof showToast === 'function') showToast('Mass archive failed', 'error');
        }
    });
});

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


function revealDoubtsButtons(conversationId, withPulse) {
    if (!conversationId) return;
    fetch('/get_messages_with_doubts/' + conversationId)
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.success && data.message_ids && data.message_ids.length > 0) {
                _applyDoubtsToCards(data.message_ids, withPulse);
            }
        })
        .catch(function() { /* silent */ });
}

// R2: Fetch-only — returns a Promise resolving with the message_ids array
// (or empty array on failure). Used for fetch-early / apply-late pattern.
function _fetchDoubtsData(conversationId) {
    if (!conversationId) return Promise.resolve([]);
    return fetch('/get_messages_with_doubts/' + conversationId)
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.success && data.message_ids && data.message_ids.length > 0) {
                return data.message_ids;
            }
            return [];
        })
        .catch(function() { return []; });
}

// R2: Apply-only — shows doubts buttons on cards that already exist in the DOM.
// Optimized: instead of N jQuery attribute-selector queries (each scanning the
// entire DOM), build a Set of message IDs and iterate the buttons once — O(buttons).
// Uses native DOM instead of jQuery .show()/.is(':hidden') to avoid forced
// synchronous layout (getComputedStyle) on each button — jQuery .show() reads
// computed styles to determine the "correct" display value, which forces a full
// style recalc on every call when the DOM is dirty.
function _applyDoubtsToCards(messageIds, withPulse) {
    if (!messageIds || messageIds.length === 0) return;
    var _t0 = performance.now();
    var idSet = new Set(messageIds.map(String));
    var _t1 = performance.now();
    var btns = document.querySelectorAll('.has-doubts-btn');
    var btnCount = btns.length, matchCount = 0, showCount = 0;
    for (var i = 0; i < btns.length; i++) {
        var el = btns[i];
        var mid = el.getAttribute('message-id');
        if (mid && idSet.has(mid)) {
            matchCount++;
            var wasHidden = (el.style.display === 'none');
            // Remove inline display:none — CSS default will take over
            el.style.display = '';
            showCount++;
            if (wasHidden && withPulse) {
                el.classList.add('doubt-new-pulse');
                el.addEventListener('animationend', function() {
                    this.classList.remove('doubt-new-pulse');
                }, { once: true });
            }
        }
    }
    var _t2 = performance.now();
    console.log('[DOUBTS-DIAG] Set build:', (_t1-_t0).toFixed(1) + 'ms, iterate+show:', (_t2-_t1).toFixed(1) + 'ms, btns:', btnCount, 'matched:', matchCount, 'shown:', showCount);
    if (withPulse && showCount > 0 && typeof showToast === 'function') {
        showToast('\u2728 Learning aids ready for your last reply', 'info');
    }
}

function loadConversations(autoselect = true) {
    return WorkspaceManager.loadConversationsWithWorkspaces(autoselect);
}

function activateChatTab() {
    // On first page load only: if 'Default Temp Chat' setting is on, skip normal
    // autoselect and go directly to createTemporaryConversation() to avoid a
    // double-render race where loadConversations + createTemporaryConversation both
    // call _processAndRenderData before jsTree's ready.jstree fires.
    if (!window._defaultTempChatCreated) {
        window._defaultTempChatCreated = true;
        var defaultTempChat = false;
        try {
            var tabName = typeof getCurrentActiveTab === 'function' ? getCurrentActiveTab() : 'assistant';
            var raw = localStorage.getItem(tabName + 'chatSettingsState');
            if (raw) { defaultTempChat = !!JSON.parse(raw).default_temp_chat; }
        } catch (_e) {}
        if (defaultTempChat) {
            // Skip loadConversations; createTemporaryConversation handles sidebar render
            WorkspaceManager.createTemporaryConversation();
            // Fall through to finish the DOM setup below
        } else {
            loadConversations();
        }
    } else {
        loadConversations();
    }
    $('#review-assistant-view').hide();
    $('#references-view').hide();
    $('#pdf-view').hide();
    $('#chat-assistant-view').show();
    // REMOVED: Auto-scroll to bottom on chat tab activation - was interrupting user reading
    // var chatView = $('#chatView');
    // chatView.scrollTop(chatView.prop('scrollHeight'));
    // REMOVED: Auto-focus on messageText causes soft keyboard on mobile/tablet.
    // $('#messageText').focus();
    $("#chat-pdf-content").addClass('d-none');
    $("#chat-content").removeClass('d-none');
    pdfTabIsActive();
    // toggleSidebar();
    var otherSidebar = $('#doc-keys-sidebar');
    var sidebar = $('#chat-assistant-sidebar');
    sidebar.addClass('d-none');
    otherSidebar.addClass('d-none');
    var contentCol = $('#content-col');
    contentCol.removeClass('col-md-9').addClass('col-md-12');
    var contentCol = $('#chat-assistant');
    contentCol.removeClass('col-md-9').addClass('col-md-12');
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


// ---------------------------------------------------------------------------
// openAsideChatModal: opens the temp LLM chat modal pre-filled with a question,
// using the current conversation as context. Called by /aside, /btw, the aside
// button, and the Ctrl+Shift+Space shortcut.
// ---------------------------------------------------------------------------
function openAsideChatModal(questionText) {
    if (typeof TempLLMManager === 'undefined') return;
    var conversationId = (typeof ConversationManager !== 'undefined')
        ? ConversationManager.activeConversationId : null;
    var messageContext = { conversationId: conversationId };
    TempLLMManager.openTempChatModal(questionText || '', messageContext, true);
    // If there's a pre-filled question, auto-submit it after the modal opens
    if (questionText && questionText.trim().length > 0) {
        setTimeout(function() {
            var $input = $('#temp-llm-user-input');
            if ($input.length && $input.val().trim() === '') {
                $input.val(questionText.trim());
                $input.trigger('input');
            }
            $('#temp-llm-send-btn').trigger('click');
        }, 150);
    }
}

// ---------------------------------------------------------------------------

function sendMessageCallback(skipAutoClarify) {
    // Remove any existing suggestions when sending a new message
    $chatView().find('.next-question-suggestions').remove();
    skipAutoClarify = !!skipAutoClarify;
    
    already_rendering = $('#messageText').prop('working')
    if (already_rendering) {
        // Display a small modal for 5 seconds then auto-close, or close on any keypress.
        //
        // Fix (H2): two accumulation bugs patched here:
        //   1. Strip any previously-registered listener in this namespace before re-attaching.
        //      Without this, each rapid Send press while streaming stacks a new handler;
        //      pressing Escape then fires closeModal() N times (first real, rest no-ops),
        //      and the N accumulated handlers all fire on every subsequent keystroke.
        //   2. Cancel any outstanding auto-close timer before scheduling a new one.
        //      Without this, N discarded timer handles fire sequentially and each calls
        //      modal('hide') + .off() on handlers that may belong to a later invocation.
        $('#prevent-chat-rendering').modal('show');

        const closeModal = function () {
            $('#prevent-chat-rendering').modal('hide');
            $(document).off('keydown.prevent-chat-rendering click.prevent-chat-rendering');
            _preventChatRenderingTimer = null;
        };

        // Cancel any outstanding auto-close timer from a prior invocation.
        if (_preventChatRenderingTimer) {
            clearTimeout(_preventChatRenderingTimer);
        }
        _preventChatRenderingTimer = setTimeout(function () {
            closeModal();
        }, 5000);

        // Strip any previously-accumulated handler before re-registering.
        // The 200ms delay avoids catching the click that triggered this invocation.
        $(document).off('keydown.prevent-chat-rendering click.prevent-chat-rendering');
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

    // /clarify command interception: fires the clarification flow instead of sending.
    // Triggered when the user types /clarify anywhere in the message (outside backticks).
    try {
        if (!skipAutoClarify && !!options.clarify_request && messageText.trim().length > 0 &&
                typeof ClarificationsManager !== 'undefined' &&
                typeof ClarificationsManager.requestAndShowClarifications === 'function') {
            // Strip /clarify token(s) from the raw messageText preserving newlines.
            // Remove the token + surrounding horizontal whitespace on its line only,
            // then drop any lines that became entirely blank as a result.
            var clarifyCleanText = messageText
                .replace(/[ \t]*\/clarif(?:ications?|y)?\b[ \t]*/gi, '')
                .replace(/^[ \t]*\n/mg, '');
            // Trim only trailing whitespace — never leading (would eat start of message).
            clarifyCleanText = clarifyCleanText.replace(/\s+$/, '');
            if (clarifyCleanText.length > 0) {
                $('#messageText').val(clarifyCleanText);
                $('#messageText').trigger('input');
            }
            ClarificationsManager.requestAndShowClarifications(
                ConversationManager.activeConversationId,
                clarifyCleanText || messageText,
                // forceClarify=true: always show questions (never auto-send on 'not-needed').
                // autoSend=false: /clarify is explicit — user decides when to send.
                { autoSend: false, forceClarify: true }
            );
            return;
        }
    } catch (e) {
        console.warn('/clarify interception failed (proceeding without clarifications):', e);
    }

    // /aside and /btw command interception: opens temp LLM chat modal with the message as the question.
    // The message text (with token stripped) becomes the pre-filled question; modal opens with full conversation context.
    try {
        if (!!options.aside_request && messageText.trim().length > 0 &&
                typeof TempLLMManager !== 'undefined') {
            var asideText = messageText
                .replace(/[ \t]*\/(?:aside|btw)\b[ \t]*/gi, '')
                .replace(/^[ \t]*\n/mg, '')
                .replace(/\s+$/, '');
            openAsideChatModal(asideText);
            return;
        }
    } catch (e) {
        console.warn('/aside interception failed (proceeding normally):', e);
    }

    // Auto-clarify interception (optional, enabled via settings).
    // Important: this must run BEFORE we clear the textarea; otherwise the user loses their draft.
    try {
        const hasClarificationsAlready = (typeof messageText === 'string') && messageText.indexOf('\n\n[Clarifications]\n') !== -1;
        const shouldAutoClarify = !skipAutoClarify && !!options.auto_clarify && messageText.trim().length > 0 && !hasClarificationsAlready;
        if (shouldAutoClarify && typeof ClarificationsManager !== 'undefined' && typeof ClarificationsManager.requestAndShowClarifications === 'function') {
            ClarificationsManager.requestAndShowClarifications(ConversationManager.activeConversationId, messageText, { autoSend: true });
            return;
        }
    } catch (e) {
        console.warn('Auto-clarify interception failed (proceeding without clarifications):', e);
    }

    // PKB slash command interceptions: /create-memory, /create-entity, /create-context, /create-simple-memory
    // These must run BEFORE the textarea is cleared so they can grab the parsed text argument.
    // Each command clears the textarea and returns early (no AI message sent).
    try {
        // /create-memory <text>: open claim modal pre-filled + auto-fire LLM analysis
        if (options.create_memory_text && typeof PKBManager !== 'undefined') {
            var _cmText = options.create_memory_text.trim();
            if (_cmText) {
                PKBManager.openAddClaimModalWithText(_cmText);
                // Fire autofill after Bootstrap has finished showing the modal (~300 ms)
                setTimeout(function() {
                    if (typeof PKBManager.autofillClaimFields === 'function') {
                        PKBManager.autofillClaimFields();
                    }
                }, 350);
                $('#messageText').val('').trigger('change');
                return;
            }
        }

        // /create-entity <name>: open PKB modal on Entities tab, pre-fill name
        if (options.create_entity_name && typeof PKBManager !== 'undefined') {
            var _ceName = options.create_entity_name.trim();
            if (_ceName) {
                PKBManager.openPKBModal();
                // Switch to Entities tab and pre-fill once modal is visible
                $('#pkb-modal').one('shown.bs.modal', function() {
                    $('#pkb-entities-tab').tab('show');
                    setTimeout(function() {
                        $('#pkb-new-entity-name').val(_ceName).focus();
                    }, 50);
                });
                $('#messageText').val('').trigger('change');
                return;
            }
        }

        // /create-context <name>: open PKB modal on Contexts tab, pre-fill name
        if (options.create_context_name && typeof PKBManager !== 'undefined') {
            var _ccName = options.create_context_name.trim();
            if (_ccName) {
                PKBManager.openPKBModal();
                // Switch to Contexts tab and pre-fill once modal is visible
                $('#pkb-modal').one('shown.bs.modal', function() {
                    $('#pkb-contexts-tab').tab('show');
                    setTimeout(function() {
                        $('#pkb-new-context-name').val(_ccName).focus();
                    }, 50);
                });
                $('#messageText').val('').trigger('change');
                return;
            }
        }

        // /create-simple-memory <text>: silent analyze+add, toast result
        if (options.create_simple_memory_text && typeof PKBManager !== 'undefined') {
            var _csmText = options.create_simple_memory_text.trim();
            if (_csmText) {
                PKBManager.createSimpleMemory(_csmText);
                $('#messageText').val('').trigger('change');
                return;
            }
        }
    } catch (e) {
        console.warn('PKB slash command interception failed:', e);
    }


    // Clear the messageText field only when we are actually sending.
    $('#messageText').val('');
    $('#messageText').trigger('change');
    $('#messageText').attr('placeholder', 'Type your message here. Press Ctrl+K for voice input.');
    $('#messageText').prop('working', true);

    // Get pending memory attachments from PKBManager (Deliberate Memory Attachment feature)
    var attached_claim_ids = [];
    if (typeof PKBManager !== 'undefined' && PKBManager.getPendingAttachments) {
        attached_claim_ids = PKBManager.getPendingAttachments();
        // Clear pending attachments after getting them
        if (attached_claim_ids.length > 0) {
            PKBManager.clearPendingAttachments();
        }
    }
    
    // Parse @memory references from message text (Deliberate Memory Attachment feature)
    var referenced_claim_ids = [];
    var referenced_friendly_ids = [];
    if (typeof parseMemoryReferences === 'function') {
        var memoryRefs = parseMemoryReferences(messageText);
        referenced_claim_ids = memoryRefs.claimIds;
        referenced_friendly_ids = memoryRefs.friendlyIds || [];
        // Optionally clean the message text (remove @memory: refs)
        // We keep the original text for now - the backend will see both
        // messageText = memoryRefs.cleanText;
    }

    ChatManager.sendMessage(ConversationManager.activeConversationId, messageText, options, links, search, attached_claim_ids, referenced_claim_ids, referenced_friendly_ids).then(function (response) {
        if (!response.ok) {
            // Reset UI state on error
            $('#stopResponseButton').hide();
            $('#sendMessageButton').show();
            $('#messageText').prop('working', false);
            // Mark synchronously so responseWaitAndSuccessChecker skips reload
            response._errorHandled = true;

            // Try to parse error body for specific error codes
            response.clone().json().then(function (body) {
                if (body && body.code === 'conversation_not_found') {
                    // Conversation was deleted on another device — copy message,
                    // notify user, and close the tab.
                    var convId = ConversationManager.activeConversationId;
                    if (messageText && navigator.clipboard && navigator.clipboard.writeText) {
                        navigator.clipboard.writeText(messageText);
                    }
                    if (typeof showToast === 'function') {
                        showToast('This conversation has been deleted. Your message was copied to clipboard.', 'warning');
                    } else {
                        alert('This conversation has been deleted. Your message was copied to clipboard.');
                    }
                    // Remove the optimistically-rendered user message
                    var $view = (typeof $chatView === 'function') ? $chatView(convId) : $('#chatView');
                    $view.find('.card.message-card').last().remove();
                    // Close the tab and navigate away
                    if (typeof TabManager !== 'undefined' && TabManager.hasTab(convId)) {
                        TabManager.removeTab(convId);
                    }
                    // Navigate to another conversation
                    if (typeof WorkspaceManager !== 'undefined') {
                        WorkspaceManager.loadConversationsWithWorkspaces(false).done(function () {
                            if (WorkspaceManager.conversations && WorkspaceManager.conversations.length > 0) {
                                var nextId = WorkspaceManager.conversations[0].conversation_id;
                                if (typeof TabManager !== 'undefined' && TabManager.tabs.length >= 1) {
                                    TabManager.openTab(nextId, 'Untitled', true);
                                } else {
                                    ConversationManager.setActiveConversation(nextId);
                                }
                                WorkspaceManager.highlightActiveConversation(nextId);
                            }
                        });
                    }
                } else {
                    alert('An error occurred: ' + response.status);
                }
            }).catch(function () {
                alert('An error occurred: ' + response.status);
            });
            return;
        }
        // $('#messageText').val('');  // Clear the messageText field
        history_message_ids = options['history_message_ids'] || []

        // Call the renderStreamingResponse function to handle the streaming response
        renderStreamingResponse(response, ConversationManager.activeConversationId, messageText, history_message_ids);
        $('#linkInput').val('')
        $('#searchInput').val('')
        // REMOVED: Auto-focus on messageText causes soft keyboard on mobile/tablet.
        // if (!/Mobi|Android/i.test(navigator.userAgent) && !/iPhone/i.test(navigator.userAgent) && window.innerWidth > 768) {
        //     $('#messageText').focus();
        // }
        ConversationManager.fetchMemoryPad().fail(function () {
            alert('Error fetching memory pad');
        });
        
        // Trigger PKB memory update proposal check (with delay to not interrupt streaming)
        // Only check if PKBManager is available
        if (typeof PKBManager !== 'undefined' && PKBManager.checkMemoryUpdates) {
            // Skip memory update proposal for /pkb and /memory slash commands
            // (the NL agent handles its own PKB operations directly)
            if (options && options.pkb_nl_command) {
                // [DEBUG] console.log('[common-chat] Skipping checkMemoryUpdates for /pkb command');
            } else if (window.chatSettingsState && window.chatSettingsState.auto_pkb_extract === false) {
                // [DEBUG] console.log('[common-chat] Skipping checkMemoryUpdates: auto-save facts disabled');
            } else {
                setTimeout(function() {
                    var conversationSummary = '';
                    var recentTurns = [];
                    try {
                        conversationSummary = ConversationManager.currentConversationSummary || '';
                        recentTurns = ConversationManager.recentTurns || [];
                    } catch (e) {}
                    PKBManager.checkMemoryUpdates(conversationSummary, messageText, '', recentTurns);
                }, 3000);  // 3 second delay to allow streaming to start
            }
        }
    }).catch(function(error) {
        // Reset UI state on error
        $('#stopResponseButton').hide();
        $('#sendMessageButton').show();
        $('#messageText').prop('working', false);
        console.error('Error sending message:', error);
        alert('Error sending message: ' + error.message);
    });
    var chatView = $chatView();
    // chatView.scrollTop(chatView.prop('scrollHeight'));
}

// scrollToBottom — module-level guard and observer reference.
// Listeners are registered only once; _chatViewResizeObserver is stored here so
// it can be disconnected if the page is ever torn down (e.g. full SPA navigation).
var _scrollToBottomInitDone = false;
var _chatViewResizeObserver = null;

// Focus/URL-update state for the delegated card focus handler.
// Previously lived inside renderMessages' function scope, which meant each
// render created fresh closures over it. Hoisted to module scope so a single
// delegated handler can share it across all renders.
var _messageFocusTimer = null;
var _currentFocusedMessageId = null;

// Returns true if the event originated from an interactive control inside the
// card (buttons, checkboxes, dropdowns) and should NOT trigger card focus.
function _focusEventShouldBeIgnored(e) {
    return $(e.target).closest(
        '.delete-message-button, .delete-pair-button, .history-message-checkbox, ' +
        '.move-message-up-button, .move-message-down-button, .show-doubts-button, ' +
        '.ask-doubt-button, .open-artefacts-button, .has-doubts-btn, .copy-btn-header, ' +
        '.pin-message-btn, .scroll-to-bottom-btn, .header-hide-toggle, .scroll-to-top-btn, ' +
        '.dropdown, .dropdown-menu, .dropdown-item, [data-toggle="dropdown"]'
    ).length > 0;
}

// Read the message-id from a card's header attribute (stamped at render time).
function _getMessageIdFromCard(cardEl) {
    var $card = $(cardEl);
    var $header = $card.find('.card-header[message-id]').first();
    if (!$header.length) return null;
    var mid = $header.attr('message-id');
    return (mid && mid !== 'undefined') ? mid : null;
}

// Debounced URL update when a message card receives focus.
function handleMessageFocus(messageId, convId) {
    if (_messageFocusTimer) {
        clearTimeout(_messageFocusTimer);
    }
    var messageIdInUrl = getMessageIdFromUrl();
    if (_currentFocusedMessageId === messageId && messageIdInUrl === messageId) {
        return;
    }
    _currentFocusedMessageId = messageId;
    _messageFocusTimer = setTimeout(function() {
        updateUrlWithMessageId(convId, messageId);
        _messageFocusTimer = null;
    }, 1000);
}

function scrollToBottom() {
    var $scrollToBottomBtn = $('#scrollToBottomBtn');

    // Function to check the scroll position
    function checkScroll() {
        var $cv = $chatView();
        // Calculate the distance from the bottom
        var scrollTop = $cv.scrollTop();
        var scrollHeight = $cv.prop('scrollHeight');
        var chatViewHeight = $cv.innerHeight();
        var distanceFromBottom = scrollHeight - (scrollTop + chatViewHeight);

        // Show button if more than 100 pixels from the bottom and chat is visible
        chat_area = $("#chat-content");
        is_chat_visible = chat_area.is(':visible') && !chat_area.hasClass('d-none');

        if (distanceFromBottom > 100 && is_chat_visible) {
            $scrollToBottomBtn.css('bottom', '80px');
            $scrollToBottomBtn.show();
        } else {
            $scrollToBottomBtn.hide();
        }
    }

    // Always run an immediate check so button visibility is correct on every call
    // (e.g. after a conversation load), even though listener binding is guarded.
    checkScroll();

    // Only bind listeners once. A second call (e.g. accidental re-init) is a no-op
    // for the listener block but still runs the checkScroll() above.
    if (_scrollToBottomInitDone) { return; }
    _scrollToBottomInitDone = true;

    // Use a capturing scroll listener on the container so that any tab's chatView
    // scroll events are detected, plus a periodic fallback for content-height changes.
    var container = document.getElementById('chatView-container');
    if (container) {
        container.addEventListener('scroll', checkScroll, true);
    }
    setInterval(checkScroll, 2000);

    // Use .off().on() on the button to prevent click-handler stacking.
    $scrollToBottomBtn.off('click.scrollToBottom').on('click.scrollToBottom', function () {
        var $cv = $chatView();
        $cv.animate({ scrollTop: $cv.prop("scrollHeight") }, "fast");
    });

    // Final check in case the page loaded in a scrolled state
    checkScroll();
}

// Function to render next question suggestions as clickable pills
function renderNextQuestionSuggestions(conversationId, retryCount = 0) {
    // CONFIGURATION SWITCHES - Modify these as needed
    let LAYOUT_MODE = 'two_lines'; // Options: 'single_line', 'two_lines', 'one_per_line'
    const REDUCED_FONT_SIZE = true; // Set to true to use smaller fonts for better fit
    
    // Remove any existing suggestions first
    $chatView().find('.next-question-suggestions').remove();
    
    // Don't retry more than 2 times (initial + 5s + 10s)
    if (retryCount > 2) {
        // [DEBUG] console.log('Max retries reached for next question suggestions');
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
                // [DEBUG] console.log(`No suggestions found, retrying in ${retryDelay/1000}s (attempt ${retryCount + 1})`);
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
                    $chatView().find('.next-question-suggestions').remove();
                });
                
                pillsContainer.append(pill);
            });
            
            // Append to chatView
            $chatView().append(suggestionsContainer);
            
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

// =============================================================================
// PKB @Autocomplete Widget (v0.5)
// Provides inline autocomplete for @memory and @context references in chat input.
// Triggered after typing '@' followed by 1+ characters.
// =============================================================================
(function() {
    'use strict';
    
    var autocompleteState = {
        active: false,          // Whether autocomplete dropdown is visible
        query: '',              // Current search prefix (chars after @)
        atPosition: -1,         // Position of the @ character in textarea
        selectedIndex: 0,       // Currently highlighted item
        results: [],            // Combined results [{type, friendly_id, label, sublabel}]
        debounceTimer: null,
        hashDebounceTimer: null,  // Debounce timer for #folder:/#tag: autocomplete
        hashDropdown: null        // jQuery element for hash autocomplete dropdown
    };
    
    /**
     * Initialize the autocomplete widget.
     * Creates the dropdown container and binds events to the message textarea.
     */
    function initAutocomplete() {
        // Create dropdown container if it doesn't exist
        if ($('#pkb-autocomplete-dropdown').length === 0) {
            var dropdownHtml = '<div id="pkb-autocomplete-dropdown" ' +
                'style="display:none; position:absolute; z-index:1100; ' +
                'background:white; border:1px solid #dee2e6; border-radius:6px; ' +
                'box-shadow:0 4px 12px rgba(0,0,0,0.15); max-height:240px; ' +
                'overflow-y:auto; min-width:300px; max-width:500px;">' +
                '</div>';
            $('body').append(dropdownHtml);
        }
        
        var $textarea = $('#messageText');
        if ($textarea.length === 0) return;
        
        // Bind input event for detecting @ and typing
        $textarea.on('input.pkbAutocomplete', function() {
            handleInput(this);
        });
        
        // Bind keydown for navigation (up/down/enter/escape/tab)
        $textarea.on('keydown.pkbAutocomplete', function(e) {
            if (!autocompleteState.active) return;
            
            if (e.key === 'ArrowDown') {
                e.preventDefault();
                navigateAutocomplete(1);
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                navigateAutocomplete(-1);
            } else if (e.key === 'Enter' || e.key === 'Tab') {
                if (autocompleteState.results.length > 0) {
                    e.preventDefault();
                    selectAutocompleteItem(autocompleteState.selectedIndex);
                }
            } else if (e.key === 'Escape') {
                e.preventDefault();
                hideAutocomplete();
            }
        });
        
        // Hide on blur (with small delay for click handling)
        $textarea.on('blur.pkbAutocomplete', function() {
            setTimeout(function() {
                hideAutocomplete();
            }, 200);
        });
        
        // Handle clicks on autocomplete items
        $(document).on('mousedown', '#pkb-autocomplete-dropdown .pkb-ac-item', function(e) {
            e.preventDefault();
            var index = parseInt($(this).data('index'));
            selectAutocompleteItem(index);
        });
    }
    
    /**
     * Handle input changes in the textarea.
     * Detects @ character and triggers autocomplete search.
     */
    function handleInput(textarea) {
        var text = textarea.value;
        var cursorPos = textarea.selectionStart;
        
        var textBeforeCursor = text.substring(0, cursorPos);
        // Check for #folder: or #tag: autocomplete BEFORE @ check
        var hashMatch = textBeforeCursor.match(/#(folder|tag):([\w\-\.]*)$/);
        if (hashMatch) {
            var hashRefType = hashMatch[1];
            var hashPrefix = hashMatch[2];
            clearTimeout(autocompleteState.hashDebounceTimer);
            autocompleteState.hashDebounceTimer = setTimeout(function() {
                fetchHashAutocomplete(hashRefType, hashPrefix, textarea);
            }, 200);
            return;
        }
        // Clear stale hash timer if pattern no longer matches
        if (autocompleteState.hashDebounceTimer) {
            clearTimeout(autocompleteState.hashDebounceTimer);
            autocompleteState.hashDebounceTimer = null;
        }

        // Find the @ character before cursor
        var lastAtIndex = textBeforeCursor.lastIndexOf('@');
        
        if (lastAtIndex === -1) {
            hideAutocomplete();
            return;
        }
        
        // Check if @ is at start or preceded by whitespace (not part of email)
        if (lastAtIndex > 0 && !/\s/.test(text.charAt(lastAtIndex - 1))) {
            hideAutocomplete();
            return;
        }
        
        // Get the text between @ and cursor
        var prefix = textBeforeCursor.substring(lastAtIndex + 1);
        
        // Must not contain spaces (we're typing a single reference token)
        if (/\s/.test(prefix)) {
            hideAutocomplete();
            return;
        }
        
        // Need at least 1 character after @
        if (prefix.length < 1) {
            hideAutocomplete();
            return;
        }
        
        // Debounce the search
        autocompleteState.atPosition = lastAtIndex;
        autocompleteState.query = prefix;
        
        clearTimeout(autocompleteState.debounceTimer);
        autocompleteState.debounceTimer = setTimeout(function() {
            fetchAutocompleteResults(prefix, textarea);
        }, 200);
    }
    
    /**
     * Fetch autocomplete results from the server.
     */
    function fetchAutocompleteResults(prefix, textarea) {
        if (typeof PKBManager === 'undefined' || !PKBManager.searchAutocomplete) {
            return;
        }
        
        PKBManager.searchAutocomplete(prefix, 8).done(function(response) {
            var results = [];
            
            // Add memories (claims — no type suffix)
            if (response.memories && response.memories.length > 0) {
                response.memories.forEach(function(m) {
                    results.push({
                        type: 'memory',
                        friendly_id: m.friendly_id,
                        label: m.statement,
                        sublabel: m.claim_type,
                        icon: 'bi-card-text'
                    });
                });
            }
            
            // Add contexts (_context suffix)
            if (response.contexts && response.contexts.length > 0) {
                response.contexts.forEach(function(c) {
                    results.push({
                        type: 'context',
                        friendly_id: c.friendly_id,
                        label: c.name,
                        sublabel: c.claim_count + ' memories',
                        icon: 'bi-folder'
                    });
                });
            }
            
            // Add entities (_entity suffix, v0.7)
            if (response.entities && response.entities.length > 0) {
                response.entities.forEach(function(e) {
                    results.push({
                        type: 'entity',
                        friendly_id: e.friendly_id,
                        label: e.name,
                        sublabel: e.entity_type,
                        icon: 'bi-person'
                    });
                });
            }
            
            // Add tags (_tag suffix, v0.7)
            if (response.tags && response.tags.length > 0) {
                response.tags.forEach(function(t) {
                    results.push({
                        type: 'tag',
                        friendly_id: t.friendly_id,
                        label: t.name,
                        sublabel: 'tag',
                        icon: 'bi-tag'
                    });
                });
            }
            
            // Add domains (_domain suffix, v0.7)
            if (response.domains && response.domains.length > 0) {
                response.domains.forEach(function(d) {
                    results.push({
                        type: 'domain',
                        friendly_id: d.friendly_id,
                        label: d.display_name,
                        sublabel: 'domain',
                        icon: 'bi-grid'
                    });
                });
            }
            
            autocompleteState.results = results;
            autocompleteState.selectedIndex = 0;
            
            if (results.length > 0) {
                showAutocomplete(textarea);
            } else {
                hideAutocomplete();
            }
        }).fail(function() {
            hideAutocomplete();
        });
    }

    /**
     * Fetch folder or tag autocomplete results for #folder: and #tag: references.
     * @param {string} refType - 'folder' or 'tag'
     * @param {string} prefix - text typed after the colon
     * @param {HTMLElement} textarea - the chat textarea
     */
    function fetchHashAutocomplete(refType, prefix, textarea) {
        var url = '/global_docs/autocomplete?type=' + encodeURIComponent(refType)
                  + '&prefix=' + encodeURIComponent(prefix);
        $.getJSON(url, function(resp) {
            var items = refType === 'folder' ? (resp.folders || []) : (resp.tags || []);
            if (!items.length) {
                showHashAutocompleteEmpty(refType, textarea);
                return;
            }
            showHashAutocompleteDropdown(items, refType, prefix, textarea);
        }).fail(function() { hideAutocomplete(); });
    }

    /**
     * Show autocomplete dropdown for #folder: or #tag: tokens.
     * Reuses the existing autocomplete dropdown element and positioning.
     * @param {Array} items - list of folder/tag name strings
     * @param {string} refType - 'folder' or 'tag'
     * @param {string} prefix - text typed after the colon
     * @param {HTMLElement} textarea - the chat textarea
     */
    function showHashAutocompleteEmpty(refType, textarea) {
        hideAutocomplete();
        var label = refType === 'folder' ? 'No folders' : 'No tags';
        var $dropdown = $('<div class="autocomplete-dropdown"></div>')
            .css({ position: 'absolute', zIndex: 9999, background: '#fff',
                   border: '1px solid #ccc', borderRadius: '4px', padding: '8px 12px',
                   minWidth: '200px', color: '#6c757d', fontSize: '13px' })
            .text(label + ' found. Create them in Global Docs settings.');
        var $textarea = $(textarea);
        var offset = $textarea.offset();
        $dropdown.css({ left: offset.left, top: offset.top - 44 });
        $('body').append($dropdown);
        autocompleteState.hashDropdown = $dropdown;
        setTimeout(function() { $dropdown.remove(); autocompleteState.hashDropdown = null; }, 3000);
    }

    function showHashAutocompleteDropdown(items, refType, prefix, textarea) {
        hideAutocomplete();
        var label = refType === 'folder' ? 'Folders' : 'Tags';
        var $dropdown = $('<div class="autocomplete-dropdown"></div>')
            .css({ position: 'absolute', zIndex: 9999, background: '#fff',
                   border: '1px solid #ccc', borderRadius: '4px', maxHeight: '200px',
                   overflowY: 'auto', minWidth: '200px' });

        var $header = $('<div class="autocomplete-section-header px-2 py-1 text-muted small font-weight-bold"></div>')
            .text(label);
        $dropdown.append($header);

        items.forEach(function(item) {
            var displayText = typeof item === 'string' ? item : item;
            var $item = $('<div class="autocomplete-item px-2 py-1" style="cursor:pointer;"></div>')
                .text(displayText)
                .on('mouseenter', function() { $(this).css('background', '#f0f0f0'); })
                .on('mouseleave', function() { $(this).css('background', ''); })
                .on('mousedown', function(e) {
                    e.preventDefault();
                    var text = textarea.value;
                    var cursorPos = textarea.selectionStart;
                    var textBeforeCursor = text.substring(0, cursorPos);
                    var tokenStart = textBeforeCursor.lastIndexOf('#' + refType + ':');
                    if (tokenStart === -1) return;
                    var replacement = '#' + refType + ':' + displayText + ' ';
                    var newText = text.substring(0, tokenStart) + replacement + text.substring(cursorPos);
                    textarea.value = newText;
                    var newPos = tokenStart + replacement.length;
                    textarea.setSelectionRange(newPos, newPos);
                    $(textarea).trigger('input');
                    $dropdown.remove();
                    autocompleteState.hashDropdown = null;
                });
            $dropdown.append($item);
        });

        var $textarea = $(textarea);
        var offset = $textarea.offset();
        var dropHeight = Math.min(items.length * 32 + 36, 200);
        $dropdown.css({
            left: offset.left,
            top: offset.top - dropHeight - 4,
            width: Math.max(200, $textarea.width() / 2)
        });
        $('body').append($dropdown);
        autocompleteState.hashDropdown = $dropdown;

        $(document).one('click.hashautocomplete', function() {
            $dropdown.remove();
            autocompleteState.hashDropdown = null;
        });
    }
    
    /**
     * Show the autocomplete dropdown positioned near the textarea.
     */
    function showAutocomplete(textarea) {
        var $dropdown = $('#pkb-autocomplete-dropdown');
        var $textarea = $(textarea);
        
        // Position dropdown above or below the textarea
        var offset = $textarea.offset();
        var textareaHeight = $textarea.outerHeight();
        
        $dropdown.css({
            left: offset.left + 'px',
            bottom: ($(window).height() - offset.top + 4) + 'px',
            top: 'auto'
        });
        
        // Render items
        var html = '';
        autocompleteState.results.forEach(function(item, index) {
            var isSelected = index === autocompleteState.selectedIndex;
            var bgClass = isSelected ? 'background-color:#e9ecef;' : '';
            var badgeColors = { context: 'info', entity: 'primary', tag: 'success', domain: 'warning' };
            var typeLabel = item.type !== 'memory' ? 
                '<span class="badge badge-' + (badgeColors[item.type] || 'secondary') + ' badge-sm ml-1">' + item.type + '</span>' : '';
            
            html += '<div class="pkb-ac-item px-3 py-2" data-index="' + index + '" ' +
                'style="cursor:pointer; border-bottom:1px solid #f0f0f0; ' + bgClass + '">' +
                '<div class="d-flex align-items-center">' +
                    '<i class="bi ' + item.icon + ' mr-2 text-muted"></i>' +
                    '<div class="flex-grow-1" style="min-width:0;">' +
                        '<div style="font-size:13px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">' + 
                            escapeHtml(item.label) + typeLabel +
                        '</div>' +
                        '<div style="font-size:11px; color:#6c757d;">' +
                            '<code>@' + escapeHtml(item.friendly_id) + '</code> &middot; ' + 
                            escapeHtml(item.sublabel) +
                        '</div>' +
                    '</div>' +
                '</div>' +
            '</div>';
        });
        
        $dropdown.html(html).show();
        autocompleteState.active = true;
    }
    
    /**
     * Hide the autocomplete dropdown.
     */
    function hideAutocomplete() {
        $('#pkb-autocomplete-dropdown').hide();
        autocompleteState.active = false;
        autocompleteState.results = [];
        autocompleteState.selectedIndex = 0;
        if (autocompleteState.hashDropdown) {
            autocompleteState.hashDropdown.remove();
            autocompleteState.hashDropdown = null;
        }
    }
    
    /**
     * Navigate the autocomplete dropdown (up/down).
     */
    function navigateAutocomplete(direction) {
        var newIndex = autocompleteState.selectedIndex + direction;
        if (newIndex < 0) newIndex = autocompleteState.results.length - 1;
        if (newIndex >= autocompleteState.results.length) newIndex = 0;
        
        autocompleteState.selectedIndex = newIndex;
        
        // Update visual highlight
        var $items = $('#pkb-autocomplete-dropdown .pkb-ac-item');
        $items.css('background-color', '');
        $items.eq(newIndex).css('background-color', '#e9ecef');
        
        // Scroll into view
        var $dropdown = $('#pkb-autocomplete-dropdown');
        var $selected = $items.eq(newIndex);
        if ($selected.length) {
            var itemTop = $selected.position().top;
            var itemHeight = $selected.outerHeight();
            var dropdownHeight = $dropdown.height();
            var scrollTop = $dropdown.scrollTop();
            
            if (itemTop < 0) {
                $dropdown.scrollTop(scrollTop + itemTop);
            } else if (itemTop + itemHeight > dropdownHeight) {
                $dropdown.scrollTop(scrollTop + itemTop + itemHeight - dropdownHeight);
            }
        }
    }
    
    /**
     * Select an autocomplete item and insert it into the textarea.
     */
    function selectAutocompleteItem(index) {
        if (index < 0 || index >= autocompleteState.results.length) return;
        
        var item = autocompleteState.results[index];
        var $textarea = $('#messageText');
        var text = $textarea.val();
        var atPos = autocompleteState.atPosition;
        var cursorPos = $textarea[0].selectionStart;
        
        // Replace @prefix with @friendly_id followed by a space
        var replacement = '@' + item.friendly_id + ' ';
        var newText = text.substring(0, atPos) + replacement + text.substring(cursorPos);
        
        $textarea.val(newText);
        
        // Set cursor position after the inserted reference
        var newCursorPos = atPos + replacement.length;
        $textarea[0].setSelectionRange(newCursorPos, newCursorPos);
        $textarea.focus();
        
        // Trigger input event to update textarea height
        $textarea.trigger('input');
        
        hideAutocomplete();
    }
    
    // escapeHtml() is the module-level canonical function defined in common.js.
    
    // Initialize when document is ready (R4: deferred — already self-delays 500ms)
    deferReady(function() {
        setTimeout(initAutocomplete, 500);
    });
})();


// =============================================================================
// Slash Command Autocomplete v2 — Fuzzy matching, 0-char trigger, cached catalog
// Provides inline autocomplete for /command references in chat input.
// - Fetches full command catalog from GET /api/slash_commands on page load
// - Uses fuzzy matching (ported from file-browser-manager.js)
// - Shows 5 items max with scroll, grouped by category
// - Pre-selects top match; Enter/Tab to apply
// - PKB commands always available; OpenCode commands gated on checkbox
// =============================================================================
(function initSlashAutocomplete() {
    'use strict';

    // -- Cached catalog (fetched once on page load) --------------------------
    var cachedCatalog = null;
    var flatCommands = [];

    // Expose catalog globally so parseMessageForCheckBoxes.js can resolve names
    window._slashCommandCatalog = null;

    function fetchAndCacheCatalog() {
        $.get('/api/slash_commands', function(data) {
            cachedCatalog = data;
            window._slashCommandCatalog = data;
            rebuildFlatCommands();
        }).fail(function() {
            console.warn('Slash command catalog fetch failed, using fallback');
            cachedCatalog = null;
            window._slashCommandCatalog = null;
        });
    }

    function rebuildFlatCommands() {
        flatCommands = [];
        if (!cachedCatalog || !cachedCatalog.categories) return;
        cachedCatalog.categories.forEach(function(cat) {
            cat.commands.forEach(function(cmd) {
                flatCommands.push({
                    command: cmd.command,
                    description: cmd.description,
                    icon: cat.icon || 'bi-slash-circle',
                    type: cmd.type || 'toggle',
                    badge: cat.badge || null,
                    requires: cat.requires || null,
                    category: cat.name
                });
            });
        });
    }

    // -- Fallback commands (used if catalog fetch fails) ---------------------
    var FALLBACK_PKB = [
        { command: 'create-memory',        description: 'Open modal to add a memory (with AI auto-fill)',      icon: 'bi-brain',       badge: 'pkb',     category: 'PKB' },
        { command: 'create-simple-memory', description: 'Silently add a memory via AI (no modal)',             icon: 'bi-lightning',   badge: 'pkb',     category: 'PKB' },
        { command: 'create-entity',        description: 'Open modal to create an entity (person, org…)',    icon: 'bi-person-plus', badge: 'pkb',     category: 'PKB' },
        { command: 'create-context',       description: 'Open modal to create a context / memory group',       icon: 'bi-folder-plus', badge: 'pkb',     category: 'PKB' },
        { command: 'pkb',              description: 'Ask or command your personal knowledge base (NL agent)', icon: 'bi-chat-dots',   badge: 'pkb',     category: 'PKB' },
        { command: 'memory',           description: 'Alias for /pkb — natural language memory operations', icon: 'bi-chat-dots',   badge: 'pkb',     category: 'PKB' },
    ];
    var FALLBACK_OPENCODE = [
        { command: 'compact',   description: 'Compress session context to save tokens', icon: 'bi-arrows-collapse',     badge: 'opencode', requires: 'enable_opencode', category: 'OpenCode' },
        { command: 'abort',     description: 'Stop current generation',                 icon: 'bi-stop-circle',         badge: 'opencode', requires: 'enable_opencode', category: 'OpenCode' },
        { command: 'new',       description: 'Create new OpenCode session',              icon: 'bi-plus-circle',         badge: 'opencode', requires: 'enable_opencode', category: 'OpenCode' },
        { command: 'sessions',  description: 'List all sessions for this conversation',  icon: 'bi-list',                badge: 'opencode', requires: 'enable_opencode', category: 'OpenCode' },
        { command: 'fork',      description: 'Branch conversation from current point',   icon: 'bi-diagram-2',           badge: 'opencode', requires: 'enable_opencode', category: 'OpenCode' },
        { command: 'summarize', description: 'Summarize session to reduce context',      icon: 'bi-file-text',           badge: 'opencode', requires: 'enable_opencode', category: 'OpenCode' },
        { command: 'status',    description: 'Show OpenCode session status',             icon: 'bi-info-circle',         badge: 'opencode', requires: 'enable_opencode', category: 'OpenCode' },
        { command: 'diff',      description: 'Show file changes in this session',        icon: 'bi-file-diff',           badge: 'opencode', requires: 'enable_opencode', category: 'OpenCode' },
        { command: 'revert',    description: 'Undo last message',                        icon: 'bi-arrow-counterclockwise', badge: 'opencode', requires: 'enable_opencode', category: 'OpenCode' },
        { command: 'mcp',       description: 'Show MCP server status',                   icon: 'bi-hdd-network',         badge: 'opencode', requires: 'enable_opencode', category: 'OpenCode' },
        { command: 'models',    description: 'Show available models',                    icon: 'bi-cpu',                 badge: 'opencode', requires: 'enable_opencode', category: 'OpenCode' },
        { command: 'help',      description: 'Show available commands',                  icon: 'bi-question-circle',     badge: 'opencode', requires: 'enable_opencode', category: 'OpenCode' }
    ];

    function buildFallbackCommands() {
        var cmds = FALLBACK_PKB.slice();
        return cmds.concat(FALLBACK_OPENCODE);
    }

    // -- Autocomplete state --------------------------------------------------
    var slashState = {
        active: false,
        query: '',
        slashPosition: -1,
        selectedIndex: 0,
        results: []
    };

    var MAX_VISIBLE_ITEMS = 5;
    var ITEM_HEIGHT_PX = 52; // approximate height of each dropdown item

    // -- Init ----------------------------------------------------------------
    function initAutocomplete() {
        if ($('#slash-autocomplete-dropdown').length === 0) {
            var maxH = (MAX_VISIBLE_ITEMS * ITEM_HEIGHT_PX) + 'px';
            var dropdownHtml = '<div id="slash-autocomplete-dropdown" ' +
                'style="display:none; position:absolute; z-index:1100; ' +
                'background:white; border:1px solid #dee2e6; border-radius:6px; ' +
                'box-shadow:0 4px 12px rgba(0,0,0,0.15); max-height:' + maxH + '; ' +
                'overflow-y:auto; min-width:320px; max-width:520px;">' +
                '</div>';
            $('body').append(dropdownHtml);
        }

        var $textarea = $('#messageText');
        if ($textarea.length === 0) return;

        $textarea.on('input.slashAutocomplete', function() {
            handleSlashInput(this);
        });

        $textarea.on('keydown.slashAutocomplete', function(e) {
            if (!slashState.active) return;

            if (e.key === 'ArrowDown') {
                e.preventDefault();
                navigateSlashAutocomplete(1);
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                navigateSlashAutocomplete(-1);
            } else if (e.key === 'Enter' || e.key === 'Tab') {
                if (slashState.results.length > 0) {
                    e.preventDefault();
                    selectSlashItem(slashState.selectedIndex);
                }
            } else if (e.key === 'Escape') {
                e.preventDefault();
                hideSlashAutocomplete();
            }
        });

        $textarea.on('blur.slashAutocomplete', function() {
            setTimeout(function() {
                hideSlashAutocomplete();
            }, 200);
        });

        $(document).on('mousedown', '#slash-autocomplete-dropdown .slash-ac-item', function(e) {
            e.preventDefault();
            var index = parseInt($(this).data('index'));
            selectSlashItem(index);
        });

        // Fetch catalog on init
        fetchAndCacheCatalog();
    }

    // -- Input handler -------------------------------------------------------
    function handleSlashInput(textarea) {
        var text = textarea.value;
        var cursorPos = textarea.selectionStart;
        var textBeforeCursor = text.substring(0, cursorPos);
        var lastSlashIndex = textBeforeCursor.lastIndexOf('/');

        if (lastSlashIndex === -1) {
            hideSlashAutocomplete();
            return;
        }

        // / must be at start or preceded by whitespace (not part of a URL)
        if (lastSlashIndex > 0 && !/\s/.test(text.charAt(lastSlashIndex - 1))) {
            hideSlashAutocomplete();
            return;
        }

        var prefix = textBeforeCursor.substring(lastSlashIndex + 1);

        // Must not contain spaces
        if (/\s/.test(prefix)) {
            hideSlashAutocomplete();
            return;
        }

        // Use cached catalog or fallback
        var opencodeEnabled = $('#settings-enable_opencode').is(':checked');
        var source = flatCommands.length > 0 ? flatCommands : buildFallbackCommands();
        var filtered = [];

        if (prefix.length === 0) {
            // Show all commands when user types just /
            source.forEach(function(cmd) {
                if (cmd.requires === 'enable_opencode' && !opencodeEnabled) return;
                filtered.push({ command: cmd.command, description: cmd.description, icon: cmd.icon, badge: cmd.badge, category: cmd.category, score: 0, matchIndexes: [] });
            });
        } else {
            // Fuzzy match against prefix
            var lowerPrefix = prefix.toLowerCase();
            source.forEach(function(cmd) {
                if (cmd.requires === 'enable_opencode' && !opencodeEnabled) return;
                var match = fuzzyMatch(lowerPrefix, cmd.command);
                if (match) {
                    filtered.push({ command: cmd.command, description: cmd.description, icon: cmd.icon, badge: cmd.badge, category: cmd.category, score: match.score, matchIndexes: match.indexes });
                }
            });
            filtered.sort(function(a, b) { return b.score - a.score; });
        }

        slashState.slashPosition = lastSlashIndex;
        slashState.query = prefix;
        slashState.results = filtered;
        slashState.selectedIndex = 0;

        if (filtered.length > 0) {
            showSlashAutocomplete(textarea);
        } else {
            hideSlashAutocomplete();
        }
    }

    // -- Highlight matched chars in command name -----------------------------
    function highlightMatches(text, indexes) {
        if (!indexes || indexes.length === 0) return escapeHtml(text);
        var indexSet = {};
        for (var i = 0; i < indexes.length; i++) indexSet[indexes[i]] = true;
        var result = '';
        for (var j = 0; j < text.length; j++) {
            var ch = escapeHtml(text[j]);
            if (indexSet[j]) {
                result += '<strong style="color:#0d6efd;">' + ch + '</strong>';
            } else {
                result += ch;
            }
        }
        return result;
    }

    // -- Badge rendering helper ----------------------------------------------
    function renderBadge(badge) {
        if (badge === 'pkb') {
            return '<span class="badge badge-sm ml-1" style="background-color:#20c997; color:white; font-size:9px;">pkb</span>';
        } else if (badge === 'opencode') {
            return '<span class="badge badge-sm ml-1" style="background-color:#6f42c1; color:white; font-size:9px;">opencode</span>';
        }
        return '';
    }

    // -- Show dropdown -------------------------------------------------------
    function showSlashAutocomplete(textarea) {
        var $dropdown = $('#slash-autocomplete-dropdown');
        var $textarea = $(textarea);
        var offset = $textarea.offset();

        $dropdown.css({
            left: offset.left + 'px',
            bottom: ($(window).height() - offset.top + 4) + 'px',
            top: 'auto'
        });

        // Render items grouped by category with thin separators
        var html = '';
        var lastCategory = null;
        slashState.results.forEach(function(item, index) {
            // Category separator
            if (item.category && item.category !== lastCategory) {
                lastCategory = item.category;
                html += '<div style="padding:3px 12px; font-size:10px; color:#6c757d; ' +
                    'text-transform:uppercase; letter-spacing:0.5px; background:#f8f9fa; ' +
                    'border-bottom:1px solid #e9ecef; font-weight:600;">' +
                    '<i class="bi ' + (item.icon || 'bi-slash-circle') + ' mr-1"></i>' +
                    escapeHtml(item.category) + '</div>';
            }

            var isSelected = index === slashState.selectedIndex;
            var bgStyle = isSelected ? 'background-color:#e9ecef;' : '';

            html += '<div class="slash-ac-item px-3 py-2" data-index="' + index + '" ' +
                'style="cursor:pointer; border-bottom:1px solid #f0f0f0; ' + bgStyle + '">' +
                '<div class="d-flex align-items-center">' +
                    '<div class="flex-grow-1" style="min-width:0;">' +
                        '<div style="font-size:13px;">' +
                            '<code>/' + highlightMatches(item.command, item.matchIndexes) + '</code>' +
                            renderBadge(item.badge) +
                        '</div>' +
                        '<div style="font-size:11px; color:#6c757d; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">' +
                            escapeHtml(item.description) +
                        '</div>' +
                    '</div>' +
                '</div>' +
            '</div>';
        });

        $dropdown.html(html).show();
        slashState.active = true;

        // Scroll selected item into view
        scrollToSelected();
    }

    // -- Hide dropdown -------------------------------------------------------
    function hideSlashAutocomplete() {
        $('#slash-autocomplete-dropdown').hide();
        slashState.active = false;
        slashState.results = [];
        slashState.selectedIndex = 0;
    }

    // -- Navigate (up/down) --------------------------------------------------
    function navigateSlashAutocomplete(direction) {
        var newIndex = slashState.selectedIndex + direction;
        if (newIndex < 0) newIndex = slashState.results.length - 1;
        if (newIndex >= slashState.results.length) newIndex = 0;

        slashState.selectedIndex = newIndex;

        var $items = $('#slash-autocomplete-dropdown .slash-ac-item');
        $items.css('background-color', '');
        $items.eq(newIndex).css('background-color', '#e9ecef');

        scrollToSelected();
    }

    // -- Scroll selected item into view --------------------------------------
    function scrollToSelected() {
        var $dropdown = $('#slash-autocomplete-dropdown');
        var $items = $dropdown.find('.slash-ac-item');
        var $selected = $items.eq(slashState.selectedIndex);
        if (!$selected.length) return;

        var itemTop = $selected.position().top;
        var itemHeight = $selected.outerHeight();
        var dropdownHeight = $dropdown.height();
        var scrollTop = $dropdown.scrollTop();

        if (itemTop < 0) {
            $dropdown.scrollTop(scrollTop + itemTop);
        } else if (itemTop + itemHeight > dropdownHeight) {
            $dropdown.scrollTop(scrollTop + itemTop + itemHeight - dropdownHeight);
        }
    }

    // -- Select item and insert into textarea --------------------------------
    function selectSlashItem(index) {
        if (index < 0 || index >= slashState.results.length) return;

        var item = slashState.results[index];
        var $textarea = $('#messageText');
        var text = $textarea.val();
        var slashPos = slashState.slashPosition;
        var cursorPos = $textarea[0].selectionStart;

        var replacement = '/' + item.command + ' ';
        var newText = text.substring(0, slashPos) + replacement + text.substring(cursorPos);

        $textarea.val(newText);

        var newCursorPos = slashPos + replacement.length;
        $textarea[0].setSelectionRange(newCursorPos, newCursorPos);
        $textarea.focus();
        $textarea.trigger('input');

        hideSlashAutocomplete();
    }

    // -- Escape HTML ---------------------------------------------------------
    // escapeHtml() is the module-level canonical function defined in common.js.

    // -- Initialize on DOM ready (R4: deferred — already self-delays 600ms) -----
    deferReady(function() {
        setTimeout(initAutocomplete, 600);
    });
})();

// @doc/ Document Reference Autocomplete
(function() {
    'use strict';

    var docAutocompleteState = {
        active: false,
        query: '',
        triggerPosition: -1,
        selectedIndex: -1,
        results: [],
        debounceTimer: null
    };

    // escapeHtml() is the module-level canonical function defined in common.js.

    function initDocAutocomplete() {
        if ($('#doc-autocomplete-dropdown').length) return;
        $('body').append(
            '<div id="doc-autocomplete-dropdown" style="' +
                'display:none;' +
                'position:fixed;' +
                'z-index:9999;' +
                'background:#fff;' +
                'border:1px solid #ced4da;' +
                'border-radius:4px;' +
                'box-shadow:0 4px 12px rgba(0,0,0,0.15);' +
                'max-height:260px;' +
                'overflow-y:auto;' +
                'min-width:280px;' +
                'max-width:480px;' +
            '"></div>'
        );

        var $textarea = $('#messageText');
        $textarea.off('.docAutocomplete');

        $textarea.on('input.docAutocomplete', function() {
            handleDocInput(this);
        });

        $textarea.on('keydown.docAutocomplete', function(e) {
            if (!docAutocompleteState.active) return;
            if (e.key === 'ArrowDown') {
                e.preventDefault();
                navigateDocAutocomplete(1);
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                navigateDocAutocomplete(-1);
            } else if (e.key === 'Enter' || e.key === 'Tab') {
                if (docAutocompleteState.selectedIndex >= 0) {
                    e.preventDefault();
                    selectDocItem(docAutocompleteState.selectedIndex);
                }
            } else if (e.key === 'Escape') {
                hideDocAutocomplete();
            }
        });

        $textarea.on('blur.docAutocomplete', function() {
            setTimeout(function() {
                hideDocAutocomplete();
            }, 200);
        });
    }

    function handleDocInput(textarea) {
        var val = textarea.value;
        var cursorPos = textarea.selectionStart;
        var textBeforeCursor = val.substring(0, cursorPos);

        // Match @doc/, #doc, or #gdoc triggers
        var match = textBeforeCursor.match(/(^|\s)(@doc\/|#gdoc|#doc)([^\s]*)$/);
        if (!match) {
            hideDocAutocomplete();
            return;
        }

        var trigger = match[2];  // '@doc/', '#doc', or '#gdoc'
        var prefix = match[3];
        // Skip if prefix looks like an already-resolved ref (e.g., #doc_1, #gdoc_12)
        if (/^_\d+$/.test(prefix)) {
            hideDocAutocomplete();
            return;
        }
        var triggerPos = textBeforeCursor.lastIndexOf(trigger);
        // scope: 'local' for #doc, 'global' for #gdoc, 'all' for @doc/
        docAutocompleteState.scope = trigger === '#doc' ? 'local' : (trigger === '#gdoc' ? 'global' : 'all');
        docAutocompleteState.trigger = trigger;
        docAutocompleteState.triggerPosition = triggerPos;
        docAutocompleteState.query = prefix;

        if (docAutocompleteState.debounceTimer) {
            clearTimeout(docAutocompleteState.debounceTimer);
        }
        docAutocompleteState.debounceTimer = setTimeout(function() {
            fetchDocAutocomplete(prefix, textarea);
        }, 150);
    }

    function fetchDocAutocomplete(prefix, textarea) {
        var conversationId = ConversationManager.activeConversationId || '';
        var scope = docAutocompleteState.scope || 'all';
        var url = '/docs/autocomplete?conversation_id=' + encodeURIComponent(conversationId) +
                  '&prefix=' + encodeURIComponent(prefix) +
                  '&scope=' + scope +
                  '&limit=10';
        $.getJSON(url, function(resp) {
            if (resp && resp.docs) {
                docAutocompleteState.results = resp.docs;
                docAutocompleteState.selectedIndex = -1;
                if (resp.docs.length > 0) {
                    docAutocompleteState.active = true;
                    showDocAutocomplete(textarea);
                } else {
                    hideDocAutocomplete();
                }
            } else {
                hideDocAutocomplete();
            }
        }).fail(function() {
            hideDocAutocomplete();
        });
    }

    function showDocAutocomplete(textarea) {
        var $dropdown = $('#doc-autocomplete-dropdown');
        var results = docAutocompleteState.results;
        var html = '';

        for (var i = 0; i < results.length; i++) {
            var doc = results[i];
            var displayName = escapeHtml(doc.display_name || doc.title || doc.ref || '');
            var refCode = escapeHtml(doc.ref || '');
            var summary = escapeHtml((doc.short_summary || '').length > 100 ? (doc.short_summary || '').substring(0, 100) + '…' : (doc.short_summary || ''));
            var isSelected = (i === docAutocompleteState.selectedIndex);
            var bgStyle = isSelected ? 'background-color:#e9ecef;' : '';

            var typeBadge = '';
            if (doc.type === 'global') {
                typeBadge = '<span class="badge badge-sm ml-1" style="background-color:#28a745;color:white;">global</span>';
            } else {
                typeBadge = '<span class="badge badge-sm ml-1" style="background-color:#007bff;color:white;">local</span>';
            }

            html += '<div class="doc-ac-item" data-index="' + i + '" style="' +
                'padding:8px 12px;' +
                'cursor:pointer;' +
                bgStyle +
            '">' +
                '<div style="display:flex;align-items:center;">' +
                    '<i class="bi bi-file-earmark-text" style="margin-right:6px;color:#6c757d;"></i>' +
                    '<span style="font-weight:500;font-size:0.9em;">' + displayName + '</span>' +
                    typeBadge +
                '</div>' +
                '<div style="font-size:0.8em;color:#6c757d;margin-top:2px;">' +
                    '<code>' + refCode + '</code>' +
                    (summary ? ' &middot; ' + summary : '') +
                '</div>' +
            '</div>';
        }

        $dropdown.html(html);

        var $textarea = $(textarea);
        var offset = $textarea.offset();
        var winHeight = $(window).height();
        var taTop = offset.top - $(window).scrollTop();
        var taLeft = offset.left - $(window).scrollLeft();

        $dropdown.css({
            left: taLeft + 'px',
            top: 'auto',
            bottom: (winHeight - taTop + 4) + 'px',
            display: 'block'
        });

        $dropdown.off('mousedown.docAc').on('mousedown.docAc', '.doc-ac-item', function(e) {
            e.preventDefault();
            var idx = parseInt($(this).data('index'), 10);
            selectDocItem(idx);
        });

        $dropdown.off('mouseover.docAc').on('mouseover.docAc', '.doc-ac-item', function() {
            var idx = parseInt($(this).data('index'), 10);
            docAutocompleteState.selectedIndex = idx;
            $dropdown.find('.doc-ac-item').css('background-color', '');
            $(this).css('background-color', '#e9ecef');
        });
    }

    function hideDocAutocomplete() {
        $('#doc-autocomplete-dropdown').hide();
        docAutocompleteState.active = false;
        docAutocompleteState.query = '';
        docAutocompleteState.triggerPosition = -1;
        docAutocompleteState.selectedIndex = -1;
        docAutocompleteState.results = [];
        if (docAutocompleteState.debounceTimer) {
            clearTimeout(docAutocompleteState.debounceTimer);
            docAutocompleteState.debounceTimer = null;
        }
    }

    function navigateDocAutocomplete(direction) {
        var results = docAutocompleteState.results;
        if (!results.length) return;
        var newIndex = docAutocompleteState.selectedIndex + direction;
        if (newIndex < 0) newIndex = results.length - 1;
        if (newIndex >= results.length) newIndex = 0;
        docAutocompleteState.selectedIndex = newIndex;
        var $dropdown = $('#doc-autocomplete-dropdown');
        $dropdown.find('.doc-ac-item').css('background-color', '');
        $dropdown.find('.doc-ac-item[data-index="' + newIndex + '"]').css('background-color', '#e9ecef');
    }

    function selectDocItem(index) {
        var results = docAutocompleteState.results;
        if (index < 0 || index >= results.length) return;
        var doc = results[index];
        var ref = doc.ref || '';

        var $textarea = $('#messageText');
        var textarea = $textarea[0];
        var val = textarea.value;
        var cursorPos = textarea.selectionStart;
        var triggerPos = docAutocompleteState.triggerPosition;

        var before = val.substring(0, triggerPos);
        var after = val.substring(cursorPos);
        var newVal = before + ref + ' ' + after;
        $textarea.val(newVal);

        var newCursorPos = triggerPos + ref.length + 1;
        textarea.setSelectionRange(newCursorPos, newCursorPos);
        $textarea.trigger('focus');

        hideDocAutocomplete();
    }

    // R4: deferred — already self-delays 700ms
    deferReady(function() {
        setTimeout(initDocAutocomplete, 700);
    });

})();

// ─────────────────────────────────────────────────────────────────────────────
// MultiSelectManager — floating action bar for batch operations on messages
// ─────────────────────────────────────────────────────────────────────────────
var MultiSelectManager = {
    _ids: [],
    _indices: [],

    count: function () { return this._ids.length; },
    getIds: function () { return this._ids.slice(); },
    getIndices: function () { return this._indices.slice(); },

    _sync: function () {
        var self = this;
        self._ids = [];
        self._indices = [];
        $(".history-message-checkbox:checked").each(function () {
            self._ids.push($(this).attr('message-id'));
            var idx = $(this).closest('.card-header').attr('message-index');
            if (idx !== undefined) self._indices.push(parseInt(idx, 10));
        });
        self._updateBar();
    },

    clearAll: function () {
        $(".history-message-checkbox:checked").prop('checked', false);
        $(".message-card").removeClass('message-selected');
        this._ids = [];
        this._indices = [];
        this._updateBar();
    },

    _updateBar: function () {
        var bar = $('#multi-select-bar');
        if (!bar.length) return;
        var n = this.count();
        if (n > 0) {
            bar.find('.ms-count').text(n + ' selected');
            bar.removeClass('d-none');
            $chatView().addClass('has-selection-bar');
        } else {
            bar.addClass('d-none');
            $chatView().removeClass('has-selection-bar');
        }
    },

    /** Concatenate selected messages as markdown (in DOM order) */
    getSelectedTexts: function () {
        var ids = this._ids;
        var texts = [];
        $('.message-card').each(function () {
            var msgId = $(this).find('.history-message-checkbox').attr('message-id');
            if (ids.indexOf(msgId) >= 0) {
                var sender = $(this).find('.card-header strong').first().text().trim() || 'Unknown';
                var text = $(this).find('.actual-card-text').first().text().trim();
                texts.push('**' + sender + ':** ' + text);
            }
        });
        return texts;
    },

    init: function () {
        var self = this;
        // Inject action bar HTML
        var isMobile = window.innerWidth < 768;
        var moreClass = isMobile ? 'dropup' : 'dropdown';
        var barHtml = '<div id="multi-select-bar" class="d-none" role="toolbar" aria-label="Selected message actions">' +
            '<span class="ms-count" aria-live="polite"></span>' +
            '<button class="btn btn-sm btn-outline-secondary ms-action" data-action="copy" title="Copy as Markdown"><i class="bi bi-clipboard"></i> Copy</button>' +
            '<button class="btn btn-sm btn-outline-danger ms-action" data-action="delete" title="Delete Selected"><i class="bi bi-trash"></i> Delete</button>' +
            '<button class="btn btn-sm btn-outline-secondary ms-action" data-action="hide" title="Hide Selected"><i class="bi bi-eye-slash"></i> Hide</button>' +
            '<div class="' + moreClass + ' d-inline-block">' +
                '<button class="btn btn-sm btn-outline-secondary dropdown-toggle" data-toggle="dropdown" aria-haspopup="true">More</button>' +
                '<div class="dropdown-menu" id="ms-more-menu">' +
                    '<a class="dropdown-item ms-action" data-action="summarize" href="#">Summarize</a>' +
                    '<a class="dropdown-item ms-action" data-action="ask" href="#">Ask Question About</a>' +
                    '<a class="dropdown-item" href="#" id="ms-preamble-toggle">Run Preamble ▸</a>' +
                    '<div id="ms-preamble-submenu" class="d-none" style="padding-left:10px;">' +
                    '</div>' +
                    '<div class="dropdown-divider"></div>' +
                    '<a class="dropdown-item ms-action" data-action="fork" href="#">Fork from Last Selected</a>' +
                    '<a class="dropdown-item ms-action" data-action="context" href="#">Use as Context</a>' +
                '</div>' +
            '</div>' +
            '<button class="btn btn-sm btn-outline-dark ms-dismiss" title="Dismiss" aria-label="Dismiss selection">&times;</button>' +
        '</div>';
        // Insert bar above chatView
        $chatView().before(barHtml);

        // Checkbox change → update state + visual
        $(document).on('change', '.history-message-checkbox', function () {
            var card = $(this).closest('.message-card');
            if ($(this).prop('checked')) {
                card.addClass('message-selected');
            } else {
                card.removeClass('message-selected');
            }
            self._sync();
        });

        // Dismiss button
        $(document).on('click', '.ms-dismiss', function () {
            self.clearAll();
        });

        // Escape key
        $(document).on('keydown', function (e) {
            if (e.key === 'Escape' && self.count() > 0) {
                self.clearAll();
            }
        });

        // Header/card tap to toggle checkbox:
        // Desktop: Cmd/Ctrl+click starts multi-select; plain click toggles when already active
        // Mobile: long-press on card starts multi-select; short tap toggles when active
        var _longPressTimer = null;
        var _longPressTriggered = false;

        // Mobile long-press to initiate multi-select.
        // When the LLM custom context menu is enabled, skip this handler so that
        // the 500 ms timer does not race with (and pre-empt) the native Android
        // text selection gesture which needs ~600-800 ms to activate.
        $(document).on('touchstart', '.message-card', function (e) {
            if ($(e.target).closest('.btn, .dropdown, .dropdown-menu, .dropdown-item, input[type="checkbox"], a, [data-toggle]').length > 0) return;
            // If the LLM context menu feature is active, let the OS handle
            // long-press for text selection instead of toggling multi-select.
            if (typeof ContextMenuManager !== 'undefined' && ContextMenuManager.isFeatureEnabled()) {
                return;
            }
            var card = $(this);
            _longPressTriggered = false;
            _longPressTimer = setTimeout(function () {
                _longPressTriggered = true;
                var cb = card.find('.history-message-checkbox');
                cb.prop('checked', !cb.prop('checked')).trigger('change');
            }, 500);
        });

        $(document).on('touchend touchmove touchcancel', '.message-card', function (e) {
            if (e.type === 'touchmove') {
                clearTimeout(_longPressTimer);
                _longPressTimer = null;
            }
            if (e.type === 'touchend' || e.type === 'touchcancel') {
                clearTimeout(_longPressTimer);
                _longPressTimer = null;
            }
        });

        // Mobile short tap toggles when multi-select is active (WhatsApp style)
        $(document).on('click', '.message-card', function (e) {
            if (_longPressTriggered) { _longPressTriggered = false; return; }
            // On mobile: only when multi-select active
            if (window.innerWidth < 768) {
                if (self.count() === 0) return;
                if ($(e.target).closest('.btn, .dropdown, .dropdown-menu, .dropdown-item, input[type="checkbox"], a, [data-toggle]').length > 0) return;
                var cb = $(this).find('.history-message-checkbox');
                cb.prop('checked', !cb.prop('checked')).trigger('change');
                // Do not stopPropagation if a dropdown is open — Bootstrap needs the
                // event to bubble to document to fire its clickout-dismiss handler.
                if ($('.dropdown-menu.show').length === 0) {
                    e.stopPropagation();
                }
                return;
            }
            // Desktop: Cmd/Ctrl+click or active multi-select
            var hasModifier = e.metaKey || e.ctrlKey;
            if (!hasModifier && self.count() === 0) return;
            if ($(e.target).closest('.btn, .dropdown, .dropdown-menu, .dropdown-item, input[type="checkbox"], a, [data-toggle]').length > 0) return;
            var cb = $(this).find('.history-message-checkbox');
            cb.prop('checked', !cb.prop('checked')).trigger('change');
            // Do not stopPropagation if a dropdown is open — Bootstrap needs the
            // event to bubble to document to fire its clickout-dismiss handler.
            if ($('.dropdown-menu.show').length === 0) {
                e.stopPropagation();
            }
        });

        // Action handlers — primary bar buttons
        $(document).on('click', '#multi-select-bar > .ms-action', function (e) {
            e.preventDefault();
            var action = $(this).data('action');
            if (!action) return;
            self._handleAction(action);
        });

        // Action handlers — items inside "More" dropdown
        $(document).on('click', '#ms-more-menu .ms-action', function (e) {
            e.preventDefault();
            e.stopPropagation();
            var action = $(this).data('action');
            if (!action) return;
            // Close dropdown manually before executing action
            $(this).closest('.dropdown, .dropup').find('[data-toggle="dropdown"]').dropdown('toggle');
            self._handleAction(action);
        });

        // Preamble submenu toggle
        $(document).on('click', '#ms-preamble-toggle', function (e) {
            e.preventDefault();
            e.stopPropagation();
            var sub = $('#ms-preamble-submenu');
            if (sub.hasClass('d-none')) {
                self._buildPreambleSubmenu();
                sub.removeClass('d-none');
            } else {
                sub.addClass('d-none');
            }
        });

        // Dynamic dropup on mobile
        $(window).on('resize', function () {
            var moreWrap = $('#multi-select-bar .dropdown, #multi-select-bar .dropup');
            if (window.innerWidth < 768) {
                moreWrap.removeClass('dropdown').addClass('dropup');
            } else {
                moreWrap.removeClass('dropup').addClass('dropdown');
            }
        });
    },

    _PREAMBLES: [
        { id: 'engineering_excellence_prompt', label: '⭐ Engineering Excellence' },
        { id: 'more_related_questions_prompt', label: '❓ Follow-up Questions' },
        { id: 'general_chain_of_density_prompt', label: '📝 Dense Summary' },
        { id: 'preamble_argumentative', label: '⚖️ Argumentative Analysis' },
        { id: 'preamble_cot', label: '🔗 Chain of Thought' },
        { id: 'improve_code_prompt', label: '💻 Improve Code' },
    ],

    _buildPreambleSubmenu: function () {
        var self = this;
        var container = $('#ms-preamble-submenu');
        container.empty();
        self._PREAMBLES.forEach(function (p) {
            container.append('<a class="dropdown-item ms-preamble-item" href="#" data-preamble="' + p.id + '">' + p.label + '</a>');
        });
        container.off('click', '.ms-preamble-item').on('click', '.ms-preamble-item', function (e) {
            e.preventDefault();
            e.stopPropagation();
            var name = $(this).data('preamble');
            self._runPreamble(name);
        });
    },

    _handleAction: function (action) {
        var self = this;
        var convId = ConversationManager.activeConversationId;
        if (!convId) return;

        switch (action) {
            case 'copy':
                var texts = self.getSelectedTexts();
                var mdText = texts.join('\n\n');
                if (navigator.clipboard && navigator.clipboard.writeText) {
                    navigator.clipboard.writeText(mdText).then(function () {
                        showToast('Copied ' + texts.length + ' messages', 'success');
                    }).catch(function () {
                        self._fallbackCopy(mdText, texts.length);
                    });
                } else {
                    self._fallbackCopy(mdText, texts.length);
                }
                self.clearAll();
                break;

            case 'delete':
                var ids = self.getIds();
                if (!confirm('Delete ' + ids.length + ' messages? This cannot be undone.')) return;
                $.ajax({
                    url: '/batch_delete_messages/' + convId,
                    type: 'POST',
                    contentType: 'application/json',
                    data: JSON.stringify({ message_ids: ids }),
                    success: function () {
                        showToast('Deleted ' + ids.length + ' messages', 'success');
                        self.clearAll();
                        ConversationManager.activeConversationId = null;
                        ConversationManager.setActiveConversation(convId);
                    },
                    error: function () { showToast('Delete failed', 'error'); }
                });
                break;

            case 'hide':
                var ids = self.getIds();
                $.ajax({
                    url: '/batch_hide_messages/' + convId,
                    type: 'POST',
                    contentType: 'application/json',
                    data: JSON.stringify({ message_ids: ids, show_hide: 'hide' }),
                    success: function () {
                        showToast(ids.length + ' messages hidden', 'success');
                        self.clearAll();
                        ConversationManager.activeConversationId = null;
                        ConversationManager.setActiveConversation(convId);
                    },
                    error: function () { showToast('Hide failed', 'error'); }
                });
                break;

            case 'context':
                // Keep checkboxes checked — send flow will pick them up
                var n = self.count();
                showToast(n + ' messages set as context', 'success');
                $('#messageText').focus();
                // Hide bar but do NOT uncheck — reset internal state so bar stays hidden
                self._ids = [];
                self._indices = [];
                $('#multi-select-bar').addClass('d-none');
                $chatView().removeClass('has-selection-bar');
                break;

            case 'ask':
                var n = self.count();
                showToast(n + ' messages set as context — type your question', 'success');
                $('#messageText').attr('placeholder', 'Ask about the selected messages...').focus();
                self._ids = [];
                self._indices = [];
                $('#multi-select-bar').addClass('d-none');
                $chatView().removeClass('has-selection-bar');
                break;

            case 'fork':
                var indices = self.getIndices();
                if (!indices.length) return;
                var maxIdx = Math.max.apply(null, indices);
                $.ajax({
                    url: '/fork_conversation/' + convId + '/' + maxIdx,
                    type: 'POST',
                    success: function (data) {
                        showToast('Forked conversation', 'success');
                        self.clearAll();
                        if (data.conversation_id) {
                            WorkspaceManager.loadConversationsWithWorkspaces(false).done(function () {
                                ConversationManager.setActiveConversation(data.conversation_id);
                                WorkspaceManager.highlightActiveConversation(data.conversation_id);
                            });
                        }
                    },
                    error: function () { showToast('Fork failed', 'error'); }
                });
                break;

            case 'summarize':
                var concatenated = self.getSelectedTexts().join('\n\n');
                if (!concatenated) {
                    showToast('No message text found to summarize', 'warning');
                    break;
                }
                if (typeof TempLLMManager !== 'undefined') {
                    TempLLMManager.preambleName = '';
                    // Delay slightly to let Bootstrap dropdown finish closing
                    setTimeout(function () {
                        TempLLMManager.executeAction('summarize_selection', concatenated, { conversationId: convId }, false);
                    }, 150);
                } else {
                    showToast('TempLLMManager not available', 'error');
                }
                self.clearAll();
                break;
        }
    },

    _fallbackCopy: function (text, count) {
        var ta = document.createElement('textarea');
        ta.value = text;
        ta.style.position = 'fixed';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.select();
        try {
            document.execCommand('copy');
            showToast('Copied ' + count + ' messages', 'success');
        } catch (_e) {
            showToast('Copy failed — try manually', 'error');
        }
        document.body.removeChild(ta);
    },

    _runPreamble: function (preambleName) {
        var self = this;
        var convId = ConversationManager.activeConversationId;
        var concatenated = self.getSelectedTexts().join('\n\n');
        if (typeof TempLLMManager !== 'undefined') {
            TempLLMManager.preambleName = preambleName;
            setTimeout(function () {
                TempLLMManager.executeAction('run_preamble', concatenated, { conversationId: convId }, false);
            }, 150);
        } else {
            showToast('TempLLMManager not available', 'error');
        }
        self.clearAll();
    }
};

// R4: deferred — MultiSelect + card focus, low risk (cards not interactive during first 100ms)
deferReady(function () {
    MultiSelectManager.init();
    // Delegated card focus handlers (bound once; survive #chatView DOM replacement).
    // Replaces the 3 per-card direct binds previously created inside renderMessages.
    // Skips cards with data-live-stream or data-live-stream-ended (those have their
    // own handlers in setupStreamingCardEventHandlers inside renderStreamingResponse).
    $(document)
        .on('click.messageCardFocus', '.message-card', function(e) {
            if ($(this).attr('data-live-stream') || $(this).attr('data-live-stream-ended')) return;
            if (_focusEventShouldBeIgnored(e)) return;
            if (typeof MultiSelectManager !== 'undefined' &&
                (MultiSelectManager.count() > 0 || e.metaKey || e.ctrlKey)) return;
            var messageId = _getMessageIdFromCard(this);
            if (messageId) {
                handleMessageFocus(messageId, ConversationManager.activeConversationId);
            }
        })
        .on('selectstart.messageCardFocus mouseup.messageCardFocus', '.message-card', function(e) {
            if ($(this).attr('data-live-stream') || $(this).attr('data-live-stream-ended')) return;
            if (_focusEventShouldBeIgnored(e)) return;
            var currentTarget = e.currentTarget;
            setTimeout(function() {
                var selection = window.getSelection();
                if (selection && selection.toString().trim().length > 0) {
                    var messageId = _getMessageIdFromCard(currentTarget);
                    if (messageId) {
                        handleMessageFocus(messageId, ConversationManager.activeConversationId);
                    }
                }
            }, 10);
        })
        .on('focus.messageCardFocus focusin.messageCardFocus', '.message-card', function(e) {
            if ($(this).attr('data-live-stream') || $(this).attr('data-live-stream-ended')) return;
            if (_focusEventShouldBeIgnored(e)) return;
            var messageId = _getMessageIdFromCard(this);
            if (messageId) {
                handleMessageFocus(messageId, ConversationManager.activeConversationId);
            }
        });

    /* ── Dropdown containment fix ────────────────────────────────────────
       content-visibility:auto on .message-card implies contain:paint which
       clips dropdown menus to the card's border box.  The CSS :has() rule
       handles modern browsers; this JS handler is a fallback that also
       toggles a .dropdown-open class on the parent .message-card so the
       CSS can disable containment while a dropdown is visible.           */
    $(document)
        .on('show.bs.dropdown', '.message-card .dropdown', function () {
            $(this).closest('.message-card').addClass('dropdown-open');
        })
        .on('hide.bs.dropdown', '.message-card .dropdown', function () {
            $(this).closest('.message-card').removeClass('dropdown-open');
        });
});
