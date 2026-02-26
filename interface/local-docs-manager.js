/**
 * local-docs-manager.js
 *
 * Provides:
 *   DocsManagerUtils  — shared MIME validation, XHR upload with progress, drop-area wiring.
 *                       Used by both LocalDocsManager and GlobalDocsManager.
 *   LocalDocsManager  — manages conversation-scoped ("local") document CRUD and the
 *                       #conversation-docs-modal UI.  Replaces the old
 *                       setupAddDocumentForm / renderDocuments combination in common-chat.js.
 *
 * This file must be loaded BEFORE global-docs-manager.js (and common-chat.js).
 */

/* ========================================================================
   DocsManagerUtils
   ======================================================================== */

/**
 * Shared utilities for file-type validation, XHR upload with progress ticks,
 * and drag-and-drop wiring.  Both LocalDocsManager and GlobalDocsManager
 * delegate to these helpers so the logic lives in one place.
 */
var DocsManagerUtils = {

    /* ------------------------------------------------------------------
       MIME helpers
       ------------------------------------------------------------------ */

    /**
     * Best-effort MIME type from the browser; falls back to an extension map.
     *
     * @param {File} file
     * @returns {string} lowercase MIME type or ''
     */
    getMimeType: function (file) {
        if (file.type) return file.type.toLowerCase();
        var ext = (file.name || '').toLowerCase().split('.').pop();
        var map = {
            'pdf':      'application/pdf',
            'doc':      'application/msword',
            'docx':     'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'html':     'text/html',  'htm': 'text/html',
            'md':       'text/markdown', 'markdown': 'text/markdown',
            'txt':      'text/plain',
            'csv':      'text/csv',  'tsv': 'text/tab-separated-values',
            'json':     'application/json',  'jsonl': 'application/x-jsonlines',
            'rtf':      'application/rtf',
            'xls':      'application/vnd.ms-excel',
            'xlsx':     'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'jpg':      'image/jpeg', 'jpeg': 'image/jpeg',
            'png':      'image/png',  'svg': 'image/svg+xml',  'bmp': 'image/bmp',
            'mp3':      'audio/mpeg', 'wav': 'audio/wav',      'webm': 'audio/webm',
            'ogg':      'audio/ogg',  'flac': 'audio/flac',    'aac': 'audio/aac',
            'm4a':      'audio/m4a',  'mp4': 'video/mp4',      'opus': 'audio/opus'
        };
        return map[ext] || '';
    },

    /**
     * Validate a file against the accept attribute of a given file input element.
     * Handles markdown and audio special cases that browsers report inconsistently.
     *
     * @param {File}    file       — the File object to validate
     * @param {jQuery}  $fileInput — the hidden <input type="file"> whose accept attr is the source of truth
     * @returns {boolean}
     */
    isValidFileType: function (file, $fileInput) {
        var validTypes = ($fileInput.attr('accept') || '').split(',').map(function (t) {
            return t.trim().toLowerCase();
        });

        var fileName     = (file.name || '').toLowerCase();
        var fileExt      = fileName.substring(fileName.lastIndexOf('.'));
        var mimeType     = DocsManagerUtils.getMimeType(file);

        // Markdown — browsers report as text/plain or application/octet-stream
        var isMarkdown   = fileExt === '.md' || fileExt === '.markdown';
        if (isMarkdown) return true;

        // Audio — MIME inconsistency across OS/browser combos
        var audioExts    = ['.mp3', '.mpeg', '.wav', '.wave', '.m4a', '.aac',
                            '.flac', '.ogg', '.oga', '.opus', '.webm', '.wma',
                            '.aiff', '.aif', '.aifc', '.mp4'];
        var audioMimes   = ['audio/mpeg', 'audio/mp3', 'audio/wav', 'audio/x-wav',
                            'audio/webm', 'audio/ogg', 'audio/flac', 'audio/x-flac',
                            'audio/aac', 'audio/m4a', 'audio/x-m4a', 'audio/mp4',
                            'video/mp4', 'audio/opus', 'audio/x-ms-wma', 'audio/aiff'];
        if (audioExts.indexOf(fileExt) !== -1 &&
            (audioMimes.indexOf(mimeType) !== -1 || mimeType === '' || mimeType === 'application/octet-stream')) {
            return true;
        }

        return validTypes.indexOf(mimeType) !== -1;
    },

    /* ------------------------------------------------------------------
       XHR upload with progress
       ------------------------------------------------------------------ */

    /**
     * Upload a File or URL string to an endpoint, showing inline XHR progress.
     *
     * Progress stages:
     *   File: 0–70 % from XHR upload.onprogress, 70–99 % via 1500 ms tick (server indexing)
     *   URL:  spinner shows "Indexing…" (no byte progress available)
     *
     * @param {string}       endpoint   — POST endpoint path
     * @param {File|string}  fileOrUrl  — File object or URL string
     * @param {Object}       opts
     * @param {jQuery}       opts.$btn        — submit button (disabled during upload)
     * @param {jQuery}       opts.$spinner    — spinner element to show/hide
     * @param {jQuery}       opts.$progress   — text element showing progress %
     * @param {string}       [opts.displayName]
     * @param {Function}     [opts.onSuccess] — called with parsed JSON response on 200
     * @param {Function}     [opts.onError]   — called with error message string
     */
    uploadWithProgress: function (endpoint, fileOrUrl, opts) {
        var $btn      = opts.$btn;
        var $spinner  = opts.$spinner;
        var $progress = opts.$progress;
        var onSuccess = opts.onSuccess || function () {};
        var onError   = opts.onError   || function (msg) { alert(msg); };

        $btn.prop('disabled', true);
        $spinner.show();
        $progress.text('0%');

        if (fileOrUrl instanceof File) {
            var xhr      = new XMLHttpRequest();
            var formData = new FormData();
            formData.append('pdf_file', fileOrUrl);
            if (opts.displayName) formData.append('display_name', opts.displayName);
            // Append any extra fields (e.g. folder_id)
            if (opts.extraFields) {
                Object.keys(opts.extraFields).forEach(function(k) {
                    if (opts.extraFields[k]) formData.append(k, opts.extraFields[k]);
                });
            }

            xhr.open('POST', endpoint, true);

            xhr.upload.onprogress = function (e) {
                if (e.lengthComputable) {
                    var pct = Math.round((e.loaded / e.total) * 70);
                    $progress.text(pct + '%');
                }
            };

            var intrvl = setInterval(function () {
                var cur = parseInt($progress.text().replace('%', ''), 10);
                if (cur >= 70 && cur < 99) {
                    $progress.text((cur + 1) + '%');
                }
            }, 1500);

            xhr.onload = function () {
                clearInterval(intrvl);
                $progress.text('100%');
                $btn.prop('disabled', false);
                $spinner.hide();

                if (xhr.status === 200) {
                    var resp = {};
                    try { resp = JSON.parse(xhr.responseText); } catch (e) {}
                    onSuccess(resp);
                } else {
                    var msg = 'Upload failed.';
                    try { msg = JSON.parse(xhr.responseText).error || msg; } catch (e) {}
                    onError(msg);
                }
            };

            xhr.onerror = function () {
                clearInterval(intrvl);
                $btn.prop('disabled', false);
                $spinner.hide();
                onError('Upload failed — network error.');
            };

            xhr.send(formData);

        } else {
            // URL path — no byte-level progress
            $progress.text('Indexing...');
            $.ajax({
                url:         endpoint,
                type:        'POST',
                contentType: 'application/json',
                data:        JSON.stringify({ pdf_url: fileOrUrl, display_name: opts.displayName || '' })
            }).done(function (resp) {
                onSuccess(resp);
            }).fail(function (jqXHR) {
                var msg = 'Upload failed.';
                try { msg = JSON.parse(jqXHR.responseText).error || msg; } catch (e) {}
                onError(msg);
            }).always(function () {
                $btn.prop('disabled', false);
                $spinner.hide();
            });
        }
    },

    /* ------------------------------------------------------------------
       Drop-area wiring
       ------------------------------------------------------------------ */

    /**
     * Wire drag-and-drop events on a drop area element.
     * Also suppresses drop events on the parent modal so they don't bubble to
     * the document-level handler in common-chat.js.
     *
     * @param {jQuery}   $dropArea   — the styled drop target div
     * @param {jQuery}   $modal      — the containing Bootstrap modal (for stopPropagation)
     * @param {jQuery}   $fileInput  — hidden <input type="file"> (for validation)
     * @param {Function} onFileDrop  — called with the dropped File object when valid
     */
    setupDropArea: function ($dropArea, $modal, $fileInput, onFileDrop) {
        $dropArea.off('dragover').on('dragover', function (e) {
            e.preventDefault();
            e.stopPropagation();
            $(this).css('background-color', '#eee');
        });

        $dropArea.off('dragleave').on('dragleave', function (e) {
            e.preventDefault();
            e.stopPropagation();
            $(this).css('background-color', 'transparent');
        });

        $dropArea.off('drop').on('drop', function (e) {
            e.preventDefault();
            e.stopPropagation();
            $(this).css('background-color', 'transparent');

            if (e.originalEvent.dataTransfer && e.originalEvent.dataTransfer.files) {
                var files = e.originalEvent.dataTransfer.files;
                if (files.length > 0) {
                    var file = files[0];
                    if (!DocsManagerUtils.isValidFileType(file, $fileInput)) {
                        alert('Invalid file type: ' + (file.type || file.name));
                        return;
                    }
                    $dropArea.text(file.name);
                    onFileDrop(file);
                }
            }
        });

        // Prevent modal from letting events reach the document-level handler
        $modal.off('dragover.docmgr').on('dragover.docmgr', function (e) {
            e.preventDefault();
            e.stopPropagation();
        });
        $modal.off('drop.docmgr').on('drop.docmgr', function (e) {
            e.preventDefault();
            e.stopPropagation();
        });
    }
};


/* ========================================================================
   LocalDocsManager
   ======================================================================== */

/**
 * Manages conversation-scoped ("local") document upload, listing, deletion,
 * download, and promotion to Global, all within the #conversation-docs-modal.
 *
 * Usage (called from common-chat.js):
 *   LocalDocsManager.setup(conversationId);   // once per conversation open
 *   LocalDocsManager.refresh(conversationId); // to reload the list
 */
var LocalDocsManager = {

    /** The conversation ID currently shown in the modal. Set by setup(). */
    conversationId: null,

    /* ------------------------------------------------------------------
       API helpers
       ------------------------------------------------------------------ */

    /**
     * GET list of documents for a conversation.
     * @param   {string} conversationId
     * @returns {jQuery.Deferred} resolves with docs array
     */
    list: function (conversationId) {
        return $.ajax({ url: '/list_documents_by_conversation/' + conversationId, type: 'GET' });
    },

    /**
     * DELETE a document from a conversation.
     * @param {string} conversationId
     * @param {string} docId
     * @returns {jQuery.Deferred}
     */
    deleteDoc: function (conversationId, docId) {
        return $.ajax({
            url: '/delete_document_from_conversation/' + conversationId + '/' + docId,
            type: 'DELETE'
        });
    },

    /**
     * Upload a File or URL to a conversation using XHR with progress.
     * On success, resets the form and refreshes the list.
     *
     * @param {string}       conversationId
     * @param {File|string}  fileOrUrl
     * @param {string}       displayName
     */
    upload: function (conversationId, fileOrUrl, displayName) {
        DocsManagerUtils.uploadWithProgress(
            '/upload_doc_to_conversation/' + conversationId,
            fileOrUrl,
            {
                $btn:        $('#conv-doc-submit-btn'),
                $spinner:    $('#conv-doc-upload-spinner'),
                $progress:   $('#conv-doc-upload-progress'),
                displayName: displayName,
                onSuccess: function () {
                    LocalDocsManager._resetForm();
                    LocalDocsManager.refresh(conversationId);
                    if (typeof showToast === 'function') showToast('Document uploaded successfully.', 'success');
                },
                onError: function (msg) {
                    alert(msg);
                }
            }
        );
    },

    /* ------------------------------------------------------------------
       List rendering
       ------------------------------------------------------------------ */

    /**
     * Render the docs list inside #conv-docs-list.
     * Each row mirrors the GlobalDocsManager.renderList row structure.
     *
     * Actions per row:
     *   View (eye)    — showPDF via /proxy_shared (same path as old renderDocuments)
     *   Download      — /download_doc_from_conversation/<conv>/<doc>
     *   Promote       — GlobalDocsManager.promote then refresh
     *   Delete        — LocalDocsManager.deleteDoc then refresh
     *
     * @param {string} conversationId
     * @param {Array}  docs           — array returned by /list_documents_by_conversation
     */
    renderList: function (conversationId, docs) {
        var $list  = $('#conv-docs-list');
        var $empty = $('#conv-docs-empty');
        $list.empty();

        if (!docs || docs.length === 0) {
            $empty.show();
            return;
        }
        $empty.hide();

        docs.forEach(function (doc, index) {
            var title         = doc.display_name || doc.title || 'Untitled';
            var sourceDisplay = doc.source || '';
            if (sourceDisplay.length > 60) sourceDisplay = sourceDisplay.substring(0, 57) + '...';

            var $item = $('<div class="list-group-item d-flex justify-content-between align-items-center"></div>');

            // Left: index badge + optional display-name badge + title + source/date
            var $info = $('<div></div>');
            $info.append($('<span class="badge badge-info mr-2"></span>').text('#doc_' + (index + 1)));
            if (doc.display_name) {
                $info.append($('<span class="badge badge-secondary mr-2"></span>').text('"' + doc.display_name + '"'));
            }
            $info.append($('<strong></strong>').text(' ' + title));
            $info.append($('<br>'));
            $info.append($('<small class="text-muted"></small>').text(sourceDisplay + (doc.created_at ? ' | ' + doc.created_at : '')));

            // Right: action buttons
            var $actions = $('<div class="d-flex flex-nowrap"></div>');

            // View button — opens PDF viewer via /proxy_shared (local doc path)
            var $viewBtn = $('<button class="btn btn-sm btn-outline-primary mr-1" title="View"></button>')
                .append('<i class="fa fa-eye"></i>');
            (function (docRef) {
                $viewBtn.click(function () {
                    showPDF(docRef.source, 'chat-pdf-content', '/proxy_shared');
                    $('#chat-pdf-content').removeClass('d-none');
                    if ($('#chat-content').length > 0) {
                        $('#chat-content').addClass('d-none');
                    }
                    ChatManager.shownDoc = docRef.source;
                    $('#conversation-docs-modal').modal('hide');
                });
            }(doc));

            // Download button
            var $downloadBtn = $('<button class="btn btn-sm btn-outline-success mr-1" title="Download"></button>')
                .append('<i class="fa fa-download"></i>');
            (function (docRef) {
                $downloadBtn.click(function () {
                    window.open('/download_doc_from_conversation/' + conversationId + '/' + docRef.doc_id, '_blank');
                });
            }(doc));

            // Promote to Global button
            var $promoteBtn = $('<button class="btn btn-sm btn-outline-info mr-1" title="Promote to Global Document"></button>')
                .append('<i class="fa fa-globe"></i>');
            (function (docRef) {
                $promoteBtn.click(function () {
                    if (confirm('Promote this document to a Global Document? It will be removed from this conversation and available across all conversations.')) {
                        GlobalDocsManager.promote(conversationId, docRef.doc_id)
                            .done(function () {
                                LocalDocsManager.refresh(conversationId);
                                if (typeof showToast === 'function') showToast('Document promoted to Global Documents.', 'success');
                            })
                            .fail(function () {
                                alert('Error promoting document.');
                            });
                    }
                });
            }(doc));

            // Delete button
            var $deleteBtn = $('<button class="btn btn-sm btn-outline-danger" title="Delete"></button>')
                .append('<i class="fa fa-trash"></i>');
            (function (docRef) {
                $deleteBtn.click(function () {
                    if (confirm('Delete document "' + title + '"? This cannot be undone.')) {
                        LocalDocsManager.deleteDoc(conversationId, docRef.doc_id)
                            .done(function () {
                                LocalDocsManager.refresh(conversationId);
                                if (typeof showToast === 'function') showToast('Document deleted.', 'success');
                            })
                            .fail(function () {
                                alert('Error deleting document.');
                            });
                    }
                });
            }(doc));

            $actions.append($viewBtn).append($downloadBtn).append($promoteBtn).append($deleteBtn);
            $item.append($info).append($actions);
            $list.append($item);
        });
    },

    /* ------------------------------------------------------------------
       Refresh
       ------------------------------------------------------------------ */

    /**
     * Fetch the document list and re-render it.
     * Accepts an optional conversationId override; falls back to the stored one.
     *
     * @param {string} [conversationId]
     */
    refresh: function (conversationId) {
        var convId = conversationId || LocalDocsManager.conversationId;
        if (!convId) return;
        LocalDocsManager.list(convId).done(function (docs) {
            LocalDocsManager.renderList(convId, docs);
        });
    },

    /* ------------------------------------------------------------------
       Form reset
       ------------------------------------------------------------------ */

    /**
     * Clear upload form fields and restore drop area default text after upload.
     */
    _resetForm: function () {
        $('#conv-doc-url').val('');
        $('#conv-doc-display-name').val('');
        $('#conv-doc-file-input').val('');
        $('#conv-doc-drop-area').text(
            'Drop a supported document or audio file here. Common formats (PDF, Word, HTML, Markdown, CSV, audio, etc.) can be uploaded directly.'
        );
    },

    /* ------------------------------------------------------------------
       Setup (called once per conversation open from common-chat.js)
       ------------------------------------------------------------------ */

    /**
     * Wire all event handlers for #conversation-docs-modal.
     * Safe to call multiple times — all handlers use .off().on().
     *
     * @param {string} conversationId
     */
    setup: function (conversationId) {
        LocalDocsManager.conversationId = conversationId;

        var $fileInput = $('#conv-doc-file-input');

        // Open modal button
        $('#conversation-docs-button').off('click').on('click', function () {
            $('#conversation-docs-modal').modal('show');
            LocalDocsManager.refresh(conversationId);
        });

        // Browse button — triggers hidden file input
        $('#conv-doc-browse-btn').off('click').on('click', function () {
            $fileInput.click();
        });

        // File input change — validate and show filename in drop area
        $fileInput.off('change').on('change', function () {
            var file = this.files && this.files[0];
            if (file) {
                if (!DocsManagerUtils.isValidFileType(file, $fileInput)) {
                    alert('Invalid file type: ' + (file.type || file.name));
                    $(this).val('');
                    return;
                }
                $('#conv-doc-drop-area').text(file.name);
            }
        });

        // Drop area wiring (stopPropagation prevents document-level handler)
        DocsManagerUtils.setupDropArea(
            $('#conv-doc-drop-area'),
            $('#conversation-docs-modal'),
            $fileInput,
            function (file) {
                var displayName = $('#conv-doc-display-name').val().trim();
                LocalDocsManager.upload(conversationId, file, displayName);
            }
        );

        // Form submit (URL or file)
        $('#conv-doc-upload-form').off('submit').on('submit', function (e) {
            e.preventDefault();
            var urlVal      = $('#conv-doc-url').val().trim();
            var displayName = $('#conv-doc-display-name').val().trim();
            var fileInput   = document.getElementById('conv-doc-file-input');

            var fileOrUrl = null;
            if (fileInput.files && fileInput.files.length > 0) {
                fileOrUrl = fileInput.files[0];
                if (!DocsManagerUtils.isValidFileType(fileOrUrl, $fileInput)) {
                    alert('Invalid file type: ' + (fileOrUrl.type || fileOrUrl.name));
                    return;
                }
            } else if (urlVal) {
                fileOrUrl = urlVal;
            } else {
                alert('Please provide a URL or select/drop a file.');
                return;
            }

            LocalDocsManager.upload(conversationId, fileOrUrl, displayName);
        });

        // Refresh button
        $('#conv-doc-refresh-btn').off('click').on('click', function () {
            LocalDocsManager.refresh(conversationId);
        });
    }
};
