/**
 * GlobalDocsManager — manages global document CRUD, drag-and-drop upload with
 * progress indication, and list rendering in the Global Documents modal.
 *
 * Upload uses XHR (not $.ajax) to get upload progress events, mirroring the
 * uploadFile_internal pattern in common-chat.js.  Drag-and-drop handlers call
 * stopPropagation() to prevent the document-level handlers in common-chat.js
 * from hijacking drops into the conversation upload endpoint.
 */
var GlobalDocsManager = {

    /* ------------------------------------------------------------------ */
    /*  API helpers                                                        */
    /* ------------------------------------------------------------------ */

    list: function () {
        return $.ajax({ url: '/global_docs/list', type: 'GET' });
    },

    deleteDoc: function (docId) {
        return $.ajax({ url: '/global_docs/' + docId, type: 'DELETE' });
    },

    promote: function (conversationId, docId) {
        return $.ajax({
            url: '/global_docs/promote/' + conversationId + '/' + docId,
            type: 'POST'
        });
    },

    getInfo: function (docId) {
        return $.ajax({ url: '/global_docs/info/' + docId, type: 'GET' });
    },

    /* ------------------------------------------------------------------ */
    /*  File type validation (mirrors isValidFileType in common-chat.js)   */
    /* ------------------------------------------------------------------ */

    _getMimeType: function (file) {
        // Best-effort MIME from the browser; falls back to extension mapping
        if (file.type) return file.type.toLowerCase();
        var ext = (file.name || '').toLowerCase().split('.').pop();
        var map = {
            'pdf': 'application/pdf',
            'doc': 'application/msword',
            'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'html': 'text/html', 'htm': 'text/html',
            'md': 'text/markdown', 'markdown': 'text/markdown',
            'txt': 'text/plain',
            'csv': 'text/csv', 'tsv': 'text/tab-separated-values',
            'json': 'application/json', 'jsonl': 'application/x-jsonlines',
            'rtf': 'application/rtf',
            'xls': 'application/vnd.ms-excel',
            'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
            'png': 'image/png', 'svg': 'image/svg+xml', 'bmp': 'image/bmp',
            'mp3': 'audio/mpeg', 'wav': 'audio/wav', 'webm': 'audio/webm',
            'ogg': 'audio/ogg', 'flac': 'audio/flac', 'aac': 'audio/aac',
            'm4a': 'audio/m4a', 'mp4': 'video/mp4', 'opus': 'audio/opus'
        };
        return map[ext] || '';
    },

    isValidFileType: function (file) {
        var fileInput = $('#global-doc-file-input');
        var validTypes = (fileInput.attr('accept') || '').split(',').map(function (t) {
            return t.trim().toLowerCase();
        });

        var fileName = (file.name || '').toLowerCase();
        var fileExtension = fileName.substring(fileName.lastIndexOf('.'));
        var mimeType = GlobalDocsManager._getMimeType(file);

        // Markdown special handling
        var isMarkdown = fileExtension === '.md' || fileExtension === '.markdown';
        if (isMarkdown) return true;

        // Audio special handling
        var audioExtensions = ['.mp3', '.mpeg', '.wav', '.wave', '.m4a', '.aac',
            '.flac', '.ogg', '.oga', '.opus', '.webm', '.wma', '.aiff', '.aif',
            '.aifc', '.mp4'];
        var audioMimeTypes = ['audio/mpeg', 'audio/mp3', 'audio/wav', 'audio/x-wav',
            'audio/webm', 'audio/ogg', 'audio/flac', 'audio/x-flac', 'audio/aac',
            'audio/m4a', 'audio/x-m4a', 'audio/mp4', 'video/mp4', 'audio/opus',
            'audio/x-ms-wma', 'audio/aiff'];
        if (audioExtensions.indexOf(fileExtension) !== -1 &&
            (audioMimeTypes.indexOf(mimeType) !== -1 || mimeType === '' || mimeType === 'application/octet-stream')) {
            return true;
        }

        // Standard MIME validation
        return validTypes.indexOf(mimeType) !== -1;
    },

    /* ------------------------------------------------------------------ */
    /*  XHR upload with progress (mirrors uploadFile_internal)             */
    /* ------------------------------------------------------------------ */

    /**
     * Upload a file or URL to /global_docs/upload using XHR for progress.
     *
     * @param {File|string} fileOrUrl - File object for file upload, string for URL upload.
     * @param {string} displayName - Optional display name.
     */
    upload: function (fileOrUrl, displayName) {
        var $btn = $('#global-doc-submit-btn');
        var $spinner = $('#global-doc-upload-spinner');
        var $progress = $('#global-doc-upload-progress');

        $btn.prop('disabled', true);
        $spinner.show();
        $progress.text('0%');

        if (fileOrUrl instanceof File) {
            // XHR upload for progress tracking
            var xhr = new XMLHttpRequest();
            var formData = new FormData();
            formData.append('pdf_file', fileOrUrl);
            if (displayName) formData.append('display_name', displayName);

            xhr.open('POST', '/global_docs/upload', true);

            // Upload progress: 0-70% during transfer
            xhr.upload.onprogress = function (e) {
                if (e.lengthComputable) {
                    var pct = Math.round((e.loaded / e.total) * 70);
                    $progress.text(pct + '%');
                }
            };

            // Slow tick from 70-99% while server indexes
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
                    GlobalDocsManager._resetForm();
                    GlobalDocsManager.refresh();
                    if (typeof showToast === 'function') showToast('Global document uploaded successfully.');
                } else {
                    var msg = 'Upload failed.';
                    try { msg = JSON.parse(xhr.responseText).error || msg; } catch (err) {}
                    alert(msg);
                }
            };

            xhr.onerror = function () {
                clearInterval(intrvl);
                $btn.prop('disabled', false);
                $spinner.hide();
                alert('Upload failed — network error.');
            };

            xhr.send(formData);
        } else {
            // URL upload — no progress events, just show spinner
            $progress.text('Indexing...');
            $.ajax({
                url: '/global_docs/upload',
                type: 'POST',
                contentType: 'application/json',
                data: JSON.stringify({ pdf_url: fileOrUrl, display_name: displayName || '' })
            }).done(function () {
                GlobalDocsManager._resetForm();
                GlobalDocsManager.refresh();
                if (typeof showToast === 'function') showToast('Global document uploaded successfully.');
            }).fail(function (xhr) {
                var msg = 'Upload failed.';
                try { msg = JSON.parse(xhr.responseText).error || msg; } catch (err) {}
                alert(msg);
            }).always(function () {
                $btn.prop('disabled', false);
                $spinner.hide();
            });
        }
    },

    /** Reset the upload form fields after successful upload. */
    _resetForm: function () {
        $('#global-doc-url').val('');
        $('#global-doc-display-name').val('');
        $('#global-doc-file-input').val('');
        // Restore default drop area text
        $('#global-doc-drop-area').text(
            'Drop a supported document or audio file here. Common formats (PDF, Word, HTML, Markdown, CSV, audio, etc.) can be uploaded directly.'
        );
    },

    /* ------------------------------------------------------------------ */
    /*  List rendering                                                     */
    /* ------------------------------------------------------------------ */

    renderList: function (docs) {
        var $list = $('#global-docs-list');
        var $empty = $('#global-docs-empty');
        $list.empty();

        if (!docs || docs.length === 0) {
            $empty.show();
            return;
        }
        $empty.hide();

        docs.forEach(function (doc) {
            var title = doc.display_name || doc.title || 'Untitled';
            var sourceDisplay = doc.source || doc.doc_source || '';
            if (sourceDisplay.length > 60) sourceDisplay = sourceDisplay.substring(0, 57) + '...';

            var $item = $('<div class="list-group-item d-flex justify-content-between align-items-center"></div>');

            var $info = $('<div></div>');
            $info.append($('<span class="badge badge-info mr-2"></span>').text('#gdoc_' + doc.index));
            if (doc.display_name) {
                $info.append($('<span class="badge badge-secondary mr-2"></span>').text('"' + doc.display_name + '"'));
            }
            $info.append($('<strong></strong>').text(' ' + title));
            $info.append($('<br>'));
            $info.append($('<small class="text-muted"></small>').text(sourceDisplay + ' | ' + (doc.created_at || '')));

            var $actions = $('<div class="d-flex flex-nowrap"></div>');

            var $viewBtn = $('<button class="btn btn-sm btn-outline-primary mr-1" title="View"></button>')
                .append('<i class="fa fa-eye"></i>');
            $viewBtn.click(function () {
                showPDF(doc.doc_id, "chat-pdf-content", "/global_docs/serve");
                $("#chat-pdf-content").removeClass('d-none');
                if ($("#chat-content").length > 0) {
                    $("#chat-content").addClass('d-none');
                }
                ChatManager.shownDoc = doc.doc_id;
                $('#global-docs-modal').modal('hide');
            });

            var $downloadBtn = $('<button class="btn btn-sm btn-outline-success mr-1" title="Download"></button>')
                .append('<i class="fa fa-download"></i>');
            $downloadBtn.click(function () {
                window.open('/global_docs/download/' + doc.doc_id, '_blank');
            });

            var $deleteBtn = $('<button class="btn btn-sm btn-outline-danger" title="Delete"></button>')
                .append('<i class="fa fa-trash"></i>');
            $deleteBtn.click(function () {
                if (confirm('Delete global document "' + title + '"? This cannot be undone.')) {
                    GlobalDocsManager.deleteDoc(doc.doc_id).done(function () {
                        GlobalDocsManager.refresh();
                        if (typeof showToast === 'function') showToast('Global document deleted.');
                    }).fail(function () {
                        alert('Error deleting global document.');
                    });
                }
            });

            $actions.append($viewBtn).append($downloadBtn).append($deleteBtn);
            $item.append($info).append($actions);
            $list.append($item);
        });
    },

    refresh: function () {
        GlobalDocsManager.list().done(function (docs) {
            GlobalDocsManager.renderList(docs);
        });
    },

    /* ------------------------------------------------------------------ */
    /*  Setup: event bindings including drag-and-drop                      */
    /* ------------------------------------------------------------------ */

    setup: function () {
        // Open modal
        $('#global-docs-button').off('click').on('click', function () {
            $('#global-docs-modal').modal('show');
            GlobalDocsManager.refresh();
        });

        // Browse button triggers hidden file input
        $('#global-doc-browse-btn').off('click').on('click', function () {
            $('#global-doc-file-input').click();
        });

        // File input change — validate and show name
        $('#global-doc-file-input').off('change').on('change', function () {
            var file = this.files && this.files[0];
            if (file) {
                if (!GlobalDocsManager.isValidFileType(file)) {
                    alert('Invalid file type: ' + (file.type || file.name));
                    $(this).val('');
                    return;
                }
                // Show filename in the drop area as feedback
                $('#global-doc-drop-area').text(file.name);
            }
        });

        // --- Drag and drop on the drop area ---
        // CRITICAL: stopPropagation prevents the document-level handlers in
        // common-chat.js from hijacking the drop and uploading to conversation.
        var $dropArea = $('#global-doc-drop-area');

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
                    var file = files[0]; // single file upload
                    if (!GlobalDocsManager.isValidFileType(file)) {
                        alert('Invalid file type: ' + (file.type || file.name));
                        return;
                    }
                    // Show filename in drop area
                    $('#global-doc-drop-area').text(file.name);
                    // Upload immediately
                    var displayName = $('#global-doc-display-name').val().trim();
                    GlobalDocsManager.upload(file, displayName);
                }
            }
        });

        // Also prevent the modal itself from letting events bubble to document
        $('#global-docs-modal').off('dragover.gdoc').on('dragover.gdoc', function (e) {
            e.preventDefault();
            e.stopPropagation();
        });
        $('#global-docs-modal').off('drop.gdoc').on('drop.gdoc', function (e) {
            e.preventDefault();
            e.stopPropagation();
        });

        // Form submit
        $('#global-doc-upload-form').off('submit').on('submit', function (e) {
            e.preventDefault();
            var fileInput = document.getElementById('global-doc-file-input');
            var urlVal = $('#global-doc-url').val().trim();
            var displayName = $('#global-doc-display-name').val().trim();

            var fileOrUrl = null;
            if (fileInput.files && fileInput.files.length > 0) {
                fileOrUrl = fileInput.files[0];
                if (!GlobalDocsManager.isValidFileType(fileOrUrl)) {
                    alert('Invalid file type: ' + (fileOrUrl.type || fileOrUrl.name));
                    return;
                }
            } else if (urlVal) {
                fileOrUrl = urlVal;
            } else {
                alert('Please provide a URL or select/drop a file.');
                return;
            }

            GlobalDocsManager.upload(fileOrUrl, displayName);
        });

        // Refresh button
        $('#global-doc-refresh-btn').off('click').on('click', function () {
            GlobalDocsManager.refresh();
        });
    }
};

$(document).ready(function () {
    GlobalDocsManager.setup();
});
