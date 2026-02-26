/**
 * GlobalDocsManager — manages global document CRUD, drag-and-drop upload with
 * progress indication, and list rendering in the Global Documents modal.
 *
 * Delegates to DocsManagerUtils (defined in local-docs-manager.js, loaded before
 * this file) for MIME validation, XHR upload with progress, and drop-area wiring.
 *
 * Requires: local-docs-manager.js (DocsManagerUtils) to be loaded first.
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
    /*  File type validation — delegates to DocsManagerUtils               */
    /* ------------------------------------------------------------------ */

    isValidFileType: function (file) {
        return DocsManagerUtils.isValidFileType(file, $('#global-doc-file-input'));
    },

    /* ------------------------------------------------------------------ */
    /*  XHR upload with progress — delegates to DocsManagerUtils          */
    /* ------------------------------------------------------------------ */

    /**
     * Upload a file or URL to /global_docs/upload using XHR for progress.
     *
     * @param {File|string} fileOrUrl - File object for file upload, string for URL upload.
     * @param {string} displayName - Optional display name.
     */
    upload: function (fileOrUrl, displayName) {
        DocsManagerUtils.uploadWithProgress('/global_docs/upload', fileOrUrl, {
            $btn:        $('#global-doc-submit-btn'),
            $spinner:    $('#global-doc-upload-spinner'),
            $progress:   $('#global-doc-upload-progress'),
            displayName: displayName,
            onSuccess: function () {
                GlobalDocsManager._resetForm();
                GlobalDocsManager.refresh();
                if (typeof showToast === 'function') showToast('Global document uploaded successfully.');
            },
            onError: function (msg) {
                alert(msg);
            }
        });
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
        DocsManagerUtils.setupDropArea(
            $('#global-doc-drop-area'),
            $('#global-docs-modal'),
            $('#global-doc-file-input'),
            function (file) {
                var displayName = $('#global-doc-display-name').val().trim();
                GlobalDocsManager.upload(file, displayName);
            }
        );

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
