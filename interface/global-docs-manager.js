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
    _viewMode: 'list',
    _folderCache: [],
    _userHash: null,


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
    upload: function (fileOrUrl, displayName, folderId) {
        DocsManagerUtils.uploadWithProgress('/global_docs/upload', fileOrUrl, {
            $btn:        $('#global-doc-submit-btn'),
            $spinner:    $('#global-doc-upload-spinner'),
            $progress:   $('#global-doc-upload-progress'),
            displayName: displayName,
            extraFields: { folder_id: folderId || '' },
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
            $item.attr('data-doc-id', doc.doc_id)
                 .attr('data-title', (title + ' ' + (doc.display_name || '')).toLowerCase())
                 .attr('data-tags', (doc.tags || []).join(',').toLowerCase());

            var $info = $('<div></div>');
            $info.append($('<span class="badge badge-info mr-2"></span>').text('#gdoc_' + doc.index));
            if (doc.display_name) {
                $info.append($('<span class="badge badge-secondary mr-2"></span>').text('"' + doc.display_name + '"'));
            }
            $info.append($('<strong></strong>').text(' ' + title));
            $info.append($('<br>'));
            $info.append($('<small class="text-muted"></small>').text(sourceDisplay + ' | ' + (doc.created_at || '')));

            // Tags
            var tags = doc.tags || [];
            var $tagWrap = $('<div class="mt-1"></div>');
            tags.forEach(function(tag) {
                $tagWrap.append(
                    $('<span class="badge badge-pill badge-secondary mr-1" style="cursor:pointer;"></span>')
                        .text(tag)
                        .on('click', function() {
                            $('#global-docs-filter').val(tag);
                            GlobalDocsManager.filterDocList(tag);
                        })
                );
            });
            // Tag add button
            var $addTagBtn = $('<button class="btn btn-link btn-sm p-0 ml-1" title="Edit tags"><i class="fa fa-tag fa-xs"></i></button>');
            $addTagBtn.on('click', function(e) {
                e.stopPropagation();
                GlobalDocsManager.openTagEditor(doc.doc_id, tags, $tagWrap);
            });
            $tagWrap.append($addTagBtn);
            $info.append($tagWrap);

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

    filterDocList: function(query) {
        var q = (query || '').toLowerCase().trim();
        $('#global-docs-list .list-group-item').each(function() {
            var title = ($(this).data('title') || '').toLowerCase();
            var tags = ($(this).data('tags') || '').toLowerCase();
            var show = !q || title.indexOf(q) !== -1 || tags.indexOf(q) !== -1;
            $(this).toggle(show);
        });
    },

    openTagEditor: function(docId, currentTags, $container) {
        // Remove any existing editor
        $container.find('.tag-editor-input').remove();
        var $input = $('<input type="text" class="form-control form-control-sm tag-editor-input mt-1">')
            .attr('placeholder', 'Tags (comma-separated)')
            .val(currentTags.join(', '));
        $container.append($input);
        $input.focus();
        function save() {
            var newTags = $input.val().split(',').map(function(t) { return t.trim().toLowerCase(); }).filter(Boolean);
            $.ajax({
                url: '/global_docs/' + docId + '/tags',
                method: 'POST',
                contentType: 'application/json',
                data: JSON.stringify({ tags: newTags }),
                success: function() { GlobalDocsManager.refresh(); }
            });
        }
        $input.on('keydown', function(e) {
            if (e.key === 'Enter') { save(); }
            if (e.key === 'Escape') { $input.remove(); }
        });
        $input.on('blur', function() { setTimeout(function() { $input.remove(); }, 200); });
    },

    _loadFolderCache: function() {
        $.getJSON('/doc_folders', function(resp) {
            if (resp.status === 'ok') {
                GlobalDocsManager._folderCache = resp.folders || [];
                // Populate folder picker
                var $sel = $('#global-doc-folder-select');
                $sel.find('option:not(:first)').remove();
                GlobalDocsManager._folderCache.forEach(function(f) {
                    $sel.append($('<option></option>').val(f.folder_id).text(f.name));
                });
            }
        });
    },

    refresh: function () {
        GlobalDocsManager.list().done(function (docs) {
            GlobalDocsManager.renderList(docs);
            // Cache user hash for file browser navigation
            if (docs && docs.length > 0 && !GlobalDocsManager._userHash) {
                var storage = docs[0].doc_storage || '';
                var match = storage.match(/storage\/global_docs\/([^\/]+)\//);
                if (match) GlobalDocsManager._userHash = match[1];
            }
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

            GlobalDocsManager.upload(fileOrUrl, displayName, $('#global-doc-folder-select').val() || null);
        });

        // Refresh button
        $('#global-doc-refresh-btn').off('click').on('click', function () {
            GlobalDocsManager.refresh();
        });

        // View switcher
        $('#global-docs-view-switcher').on('click', 'button[data-view]', function() {
            var view = $(this).data('view');
            GlobalDocsManager._viewMode = view;
            localStorage.setItem('globalDocsViewMode', view);
            $('#global-docs-view-switcher button').removeClass('active');
            $(this).addClass('active');
            if (view === 'list') {
                $('#global-docs-view-list').show();
                $('#global-docs-view-folder').hide();
                $('#global-docs-manage-folders-btn').hide();
                $('#global-docs-dialog').removeClass('modal-xl').addClass('modal-lg');
            } else {
                $('#global-docs-view-list').hide();
                $('#global-docs-view-folder').show();
                $('#global-docs-manage-folders-btn').show();
                $('#global-docs-dialog').removeClass('modal-lg').addClass('modal-xl');
            }
        });

        // Restore saved view mode
        var savedView = localStorage.getItem('globalDocsViewMode') || 'list';
        if (savedView !== 'list') {
            $('#global-docs-view-switcher button[data-view="' + savedView + '"]').trigger('click');
        }

        // Filter bar
        $('#global-docs-filter').on('input', function() {
            GlobalDocsManager.filterDocList($(this).val());
        });

        // Manage Folders button
        $('#global-docs-manage-folders-btn').on('click', function() {
            if (typeof FileBrowserManager === 'undefined') {
                alert('File browser not available.');
                return;
            }
            FileBrowserManager.configure({
                onMove: function(srcPath, destPath, done) {
                    var srcParts = srcPath.replace(/\\/g, '/').split('/');
                    var docId = srcParts[srcParts.length - 1];
                    var destParts = destPath.replace(/\\/g, '/').split('/');
                    // destParts last element = docId basename, second-to-last = parent folder name
                    var parentName = destParts.length >= 2 ? destParts[destParts.length - 2] : null;
                    var folder = parentName
                        ? (GlobalDocsManager._folderCache || []).find(function(f) { return f.name === parentName; })
                        : null;
                    var folderId = folder ? folder.folder_id : 'root';
                    if (!docId || docId.length < 8) { done('Cannot determine doc_id'); return; }
                    $.ajax({
                        url: '/doc_folders/' + folderId + '/assign',
                        method: 'POST',
                        contentType: 'application/json',
                        data: JSON.stringify({ doc_id: docId }),
                        success: function(r) {
                            GlobalDocsManager.refresh();
                            done(r.status === 'ok' ? null : (r.error || 'Assign failed'));
                        },
                        error: function(xhr) {
                            var msg = 'Assign failed';
                            try { msg = JSON.parse(xhr.responseText).error || msg; } catch(e) {}
                            done(msg);
                        }
                    });
                }
            });
            // Navigate to global docs storage root
            var startPath = GlobalDocsManager._userHash
                ? 'storage/global_docs/' + GlobalDocsManager._userHash
                : 'storage/global_docs';
            FileBrowserManager.open(startPath);
            $('#global-docs-modal').modal('hide');
        });

        // Load folder cache when modal opens
        $('#global-docs-button').off('click.folders').on('click.folders', function() {
            GlobalDocsManager._loadFolderCache();
        });
    }
};

$(document).ready(function () {
    GlobalDocsManager.setup();
});
