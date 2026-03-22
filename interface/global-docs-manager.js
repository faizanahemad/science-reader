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
    _fileBrowser: null,


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
     * @param {string} folderId - Optional folder ID.
     * @param {string} tags - Optional comma-separated tags string.
     */
    upload: function (fileOrUrl, displayName, folderId, tags) {
        var priority = $('#global-doc-priority').val();
        var dateWritten = $('#global-doc-date-written').val();
        var extra = { folder_id: folderId || '', tags: tags || '' };
        if (priority) extra.priority = priority;
        if (dateWritten) extra.date_written = dateWritten;
        DocsManagerUtils.uploadWithProgress('/global_docs/upload', fileOrUrl, {
            $btn:        $('#global-doc-submit-btn'),
            $spinner:    $('#global-doc-upload-spinner'),
            $progress:   $('#global-doc-upload-progress'),
            displayName: displayName,
            extraFields: extra,
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
        $('#global-doc-tags-input').val('');
        $('#global-doc-folder-select').val('');
        $('#global-doc-priority').val('3');
        $('#global-doc-date-written').val('');
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

        var priorityLabels = {1: 'Very Low', 2: 'Low', 3: 'Medium', 4: 'High', 5: 'Very High'};

        docs.forEach(function (doc) {
            var title = doc.display_name || doc.title || 'Untitled';
            var sourceDisplay = doc.source || doc.doc_source || '';
            if (sourceDisplay.length > 60) sourceDisplay = sourceDisplay.substring(0, 57) + '...';
            var isDeprecated = !!doc.deprecated;

            var $item = $('<div class="list-group-item"></div>');
            $item.attr('data-doc-id', doc.doc_id)
                 .attr('data-title', (title + ' ' + (doc.display_name || '')).toLowerCase())
                 .attr('data-tags', (doc.tags || []).join(',').toLowerCase());
            if (isDeprecated) $item.css('opacity', '0.5');

            // --- Top row: info + action buttons ---
            var $topRow = $('<div class="d-flex flex-wrap justify-content-between align-items-start"></div>');

            var $info = $('<div></div>');
            $info.append($('<span class="badge badge-info mr-2"></span>').text('#gdoc_' + doc.index));
            if (doc.display_name) {
                $info.append($('<span class="badge badge-secondary mr-2"></span>').text('"' + doc.display_name + '"'));
            }
            if (isDeprecated) {
                $info.append($('<span class="badge badge-danger mr-2"></span>').text('DEPRECATED'));
                $info.append($('<strong style="text-decoration: line-through;"></strong>').text(' ' + title));
            } else {
                $info.append($('<strong></strong>').text(' ' + title));
            }
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

            var $actions = $('<div class="d-flex flex-nowrap flex-shrink-0 mt-1"></div>');

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

            var $editBtn = $('<button class="btn btn-sm btn-outline-secondary mr-1" title="Edit / Replace Document"></button>')
                .append('<i class="fa fa-pencil"></i>');
            (function (docRef) {
                $editBtn.click(function () {
                    GlobalDocsManager.openEditModal(docRef);
                });
            }(doc));

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

            $actions.append($viewBtn).append($downloadBtn).append($editBtn).append($deleteBtn);
            $topRow.append($info).append($actions);
            $item.append($topRow);

            // --- Metadata row: priority, date_written, deprecated ---
            var $metaRow = $('<div class="d-flex align-items-center mt-1" style="gap:10px; flex-wrap:wrap;"></div>');

            // Priority dropdown
            var $priSelect = $('<select class="form-control form-control-sm" style="width:auto; display:inline-block; font-size:0.8rem;"></select>');
            [5,4,3,2,1].forEach(function(v) { $priSelect.append($('<option></option>').val(v).text(priorityLabels[v])); });
            $priSelect.val(doc.priority || 3);
            (function(docId) {
                $priSelect.on('change', function() {
                    GlobalDocsManager._updateMetadata(docId, {priority: parseInt($(this).val(), 10)});
                });
            })(doc.doc_id);
            $metaRow.append($('<label class="small text-muted mb-0 mr-1">Priority:</label>')).append($priSelect);

            // Date written input
            var $dateInput = $('<input type="date" class="form-control form-control-sm" style="width:auto; display:inline-block; font-size:0.8rem;">');
            $dateInput.val(doc.date_written || '');
            (function(docId) {
                $dateInput.on('change', function() {
                    GlobalDocsManager._updateMetadata(docId, {date_written: $(this).val()});
                });
            })(doc.doc_id);
            $metaRow.append($('<label class="small text-muted mb-0 mr-1 ml-2">Written:</label>')).append($dateInput);

            // Deprecated checkbox
            var cbId = 'gdoc-dep-' + doc.doc_id;
            var $depCheck = $('<input type="checkbox" class="mr-1">').attr('id', cbId);
            $depCheck.prop('checked', isDeprecated);
            (function(docId) {
                $depCheck.on('change', function() {
                    GlobalDocsManager._updateMetadata(docId, {deprecated: $(this).is(':checked')});
                });
            })(doc.doc_id);
            $metaRow.append($('<label class="small text-muted mb-0 mr-1 ml-2"></label>').text('Deprecated:').attr('for', cbId)).append($depCheck);

            $item.append($metaRow);
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

    /**
     * Send a PATCH to update metadata fields for a global document.
     * @param {string} docId
     * @param {Object} fields — e.g. {priority:4}, {date_written:'2025-01-01'}, {deprecated:true}
     */
    _updateMetadata: function(docId, fields) {
        $.ajax({
            url: '/global_docs/' + docId + '/metadata',
            method: 'PATCH',
            contentType: 'application/json',
            data: JSON.stringify(fields),
            success: function() {
                GlobalDocsManager.refresh();
                if (typeof showToast === 'function') showToast('Metadata updated.');
            },
            error: function(xhr) {
                var msg = 'Error updating metadata.';
                try { msg = JSON.parse(xhr.responseText).error || msg; } catch(e) {}
                if (typeof showToast === 'function') showToast(msg, 'danger');
            }
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

    // ---- Document Edit / Replace methods ----

    openEditModal: function (doc) {
        var $modal = $('#doc-edit-modal');

        // Reset
        $('#doc-edit-file-input').val('');
        $('#doc-edit-file-selected').hide();
        $('#doc-edit-progress-area').hide();
        $('#doc-edit-save-btn').prop('disabled', false).html('<i class="fa fa-save"></i> Save Changes');
        $('#doc-edit-progress-bar').css('width', '0%').removeClass('bg-danger');

        // Current info
        $('#doc-edit-current-title').text(doc.display_name || doc.title || 'Untitled');
        $('#doc-edit-current-source').text(doc.doc_source || doc.source || '');
        $('#doc-edit-current-type').text(doc.doc_filetype || '');
        $('#docEditModalLabel').text('Edit Global Document');

        // Metadata
        $('#doc-edit-display-name').val(doc.display_name || '');
        $('#doc-edit-priority').val(doc.priority || 3);
        $('#doc-edit-date-written').val(doc.date_written || '');
        $('#doc-edit-deprecated').prop('checked', !!doc.deprecated);

        // Tags (global only)
        $('#doc-edit-tags-group').show();
        $('#doc-edit-tags').val((doc.tags || []).join(', '));

        // Folder (global only)
        $('#doc-edit-folder-group').show();
        var $folderSelect = $('#doc-edit-folder');
        $folderSelect.find('option:not(:first)').remove();
        GlobalDocsManager._folderCache.forEach(function (f) {
            $folderSelect.append($('<option>').val(f.id || f.folder_id).text(f.name));
        });
        $folderSelect.val(doc.folder_id || '');

        // Wire browse button
        $('#doc-edit-browse-btn').off('click').on('click', function () {
            $('#doc-edit-file-input').click();
        });

        // Wire drop area
        DocsManagerUtils.setupDropArea(
            $('#doc-edit-drop-area'),
            $modal,
            $('#doc-edit-file-input'),
            function (file) {
                $('#doc-edit-file-name').text(file.name || (file[0] && file[0].name) || '');
                $('#doc-edit-file-selected').show();
            }
        );

        // File selection display
        $('#doc-edit-file-input').off('change').on('change', function () {
            var file = this.files[0];
            if (file) {
                $('#doc-edit-file-name').text(file.name);
                $('#doc-edit-file-selected').show();
            }
        });
        $('#doc-edit-file-clear').off('click').on('click', function () {
            $('#doc-edit-file-input').val('');
            $('#doc-edit-file-selected').hide();
        });

        // Save
        $('#doc-edit-save-btn').off('click').on('click', function () {
            var newFile = $('#doc-edit-file-input')[0].files[0] || null;
            var metadata = {
                display_name: $('#doc-edit-display-name').val().trim() || null,
                priority: parseInt($('#doc-edit-priority').val(), 10),
                date_written: $('#doc-edit-date-written').val() || null,
                deprecated: $('#doc-edit-deprecated').is(':checked'),
            };
            var tags = $('#doc-edit-tags').val().trim();

            if (newFile) {
                GlobalDocsManager._replaceDoc(doc.doc_id, newFile, metadata, tags);
            } else {
                // Metadata-only update
                GlobalDocsManager._updateMetadata(doc.doc_id, metadata);
                // Update tags if changed
                if (tags !== (doc.tags || []).join(', ')) {
                    GlobalDocsManager._saveTags(doc.doc_id, tags);
                }
                $modal.modal('hide');
                GlobalDocsManager.refresh();
                if (typeof showToast === 'function') showToast('Document updated.', 'success');
            }
        });

        $modal.modal('show');
    },

    _replaceDoc: function (docId, file, metadata, tags) {
        var $saveBtn = $('#doc-edit-save-btn');
        var $progress = $('#doc-edit-progress-area');
        var $bar = $('#doc-edit-progress-bar');
        var $msg = $('#doc-edit-progress-message');

        $saveBtn.prop('disabled', true).html('<i class="fa fa-spinner fa-spin"></i> Replacing\u2026');
        $progress.show();
        $bar.css('width', '5%');
        $msg.text('Uploading file\u2026');

        var formData = new FormData();
        formData.append('pdf_file', file);
        if (metadata.display_name) formData.append('display_name', metadata.display_name);

        $.ajax({
            url: '/global_docs/' + docId + '/replace',
            method: 'POST',
            data: formData,
            processData: false,
            contentType: false,
            xhr: function () {
                var xhr = new XMLHttpRequest();
                xhr.upload.addEventListener('progress', function (e) {
                    if (e.lengthComputable) {
                        var pct = Math.round((e.loaded / e.total) * 30);
                        $bar.css('width', pct + '%');
                    }
                });
                return xhr;
            },
            success: function (resp) {
                if (resp && resp.task_id) {
                    GlobalDocsManager._listenReplaceProgress(
                        resp.task_id, $bar, $msg, $saveBtn, metadata, tags
                    );
                } else {
                    $progress.hide();
                    $('#doc-edit-modal').modal('hide');
                    GlobalDocsManager.refresh();
                    if (typeof showToast === 'function') showToast('Document replaced.', 'success');
                }
            },
            error: function (xhr) {
                $progress.hide();
                $saveBtn.prop('disabled', false).html('<i class="fa fa-save"></i> Save Changes');
                var msg = 'Error replacing document.';
                try { msg = JSON.parse(xhr.responseText).error || msg; } catch(e) {}
                if (typeof showToast === 'function') showToast(msg, 'danger');
            }
        });
    },

    _listenReplaceProgress: function (taskId, $bar, $msg, $saveBtn, metadata, tags) {
        var source = new EventSource('/global_docs/replace_progress/' + taskId);
        source.onmessage = function (event) {
            var data = JSON.parse(event.data);
            $msg.text(data.message || '');

            var phaseMap = {queued: 30, reading: 45, title_summary: 60, long_summary: 75, saving: 90, done: 100, error: 100};
            var pct = phaseMap[data.phase] || 35;
            $bar.css('width', pct + '%');

            if (data.status === 'completed') {
                source.close();
                if (data.new_doc_id) {
                    GlobalDocsManager._updateMetadata(data.new_doc_id, metadata);
                    if (tags) GlobalDocsManager._saveTags(data.new_doc_id, tags);
                }
                setTimeout(function () {
                    $('#doc-edit-progress-area').hide();
                    $('#doc-edit-modal').modal('hide');
                    GlobalDocsManager.refresh();
                    if (typeof showToast === 'function') showToast('Document replaced successfully.', 'success');
                }, 500);
            } else if (data.status === 'error') {
                source.close();
                $bar.addClass('bg-danger');
                $saveBtn.prop('disabled', false).html('<i class="fa fa-save"></i> Retry');
                if (typeof showToast === 'function') showToast('Replace failed: ' + data.message, 'danger');
            }
        };
        source.onerror = function () {
            source.close();
            $saveBtn.prop('disabled', false).html('<i class="fa fa-save"></i> Retry');
            if (typeof showToast === 'function') showToast('Connection lost during replacement.', 'danger');
        };
    },

    _saveTags: function (docId, tagsStr) {
        var tagList = tagsStr.split(',').map(function (t) { return t.trim().toLowerCase(); }).filter(Boolean);
        $.ajax({
            url: '/global_docs/' + docId + '/tags',
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ tags: tagList }),
        });
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

    /**
     * Open the global-docs file browser. Creates the instance on first call,
     * reuses it on subsequent calls. Hides the global-docs modal.
     */
    _openFileBrowser: function() {
        if (typeof createFileBrowser === 'undefined') {
            alert('File browser not available.');
            return;
        }
        var startPath = GlobalDocsManager._userHash
            ? 'storage/global_docs/' + GlobalDocsManager._userHash
            : 'storage/global_docs';

        if (!GlobalDocsManager._fileBrowser) {
            GlobalDocsManager._fileBrowser = createFileBrowser('global-docs-fb', {
                rootPath: startPath,
                uploadFields: {
                    populateFolders: function() {
                        return GlobalDocsManager._folderCache || [];
                    }
                },
                onMove: function(srcPath, destPath, done) {
                    var srcParts = srcPath.replace(/\\/g, '/').split('/');
                    var docId = srcParts[srcParts.length - 1];
                    var destParts = destPath.replace(/\\/g, '/').split('/');
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
                },
                onDelete: function(path, done) {
                    var parts = path.replace(/\\/g, '/').split('/').filter(Boolean);
                    var last = parts[parts.length - 1];

                    function _fallbackFsDelete(p, cb) {
                        $.ajax({
                            url: '/file-browser/delete',
                            method: 'POST',
                            contentType: 'application/json',
                            data: JSON.stringify({ path: p, recursive: true }),
                            success: function() { cb(null); },
                            error: function() { cb('Delete failed'); }
                        });
                    }

                    if (last && last.length >= 8 && last.indexOf(' ') === -1) {
                        $.ajax({
                            url: '/global_docs/' + last,
                            method: 'DELETE',
                            success: function(r) {
                                GlobalDocsManager.refresh();
                                done(r.status === 'ok' ? null : (r.error || 'Delete failed'));
                            },
                            error: function(xhr) {
                                if (xhr.status === 404) {
                                    _fallbackFsDelete(path, done);
                                } else {
                                    var msg = 'Delete failed';
                                    try { msg = JSON.parse(xhr.responseText).error || msg; } catch(e) {}
                                    done(msg);
                                }
                            }
                        });
                    } else {
                        _fallbackFsDelete(path, done);
                    }
                },
            onUpload: function(file, targetDir, done, meta) {
                // Delegate to the global docs upload pipeline so the file is
                // indexed as a global document, not just stored as a raw file.
                meta = meta || {};
                var displayName = meta.displayName || file.name;
                var folderId = meta.folderId;
                if (!folderId) {
                    // Fallback: infer folder from current directory if possible.
                    var dir = targetDir.replace(/\\/g, '/');
                    var parts = dir.split('/').filter(Boolean);
                    var folderName = parts.length > 0 ? parts[parts.length - 1] : null;
                    var folder = folderName
                        ? (GlobalDocsManager._folderCache || []).find(function(f) { return f.name === folderName; })
                        : null;
                    folderId = folder ? folder.folder_id : '';
                }
                var extraFields = { folder_id: folderId };
                if (meta.tags) extraFields.tags = meta.tags;
                DocsManagerUtils.uploadWithProgress('/global_docs/upload', file, {
                    $btn:        $(),   // no UI btn to disable — file browser owns the spinner
                    $spinner:    $(),
                    $progress:   $(),
                    displayName: displayName,
                    extraFields: extraFields,
                    onSuccess: function() {
                        GlobalDocsManager.refresh();
                        done(null);
                    },
                    onError: function(msg) {
                        done(msg);
                    }
                });
            }
        });
            GlobalDocsManager._fileBrowser.init();
        } else {
            GlobalDocsManager._fileBrowser.configure({ rootPath: startPath });
        }
        GlobalDocsManager._fileBrowser.open(startPath);
        $('#global-docs-modal').modal('hide');
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
                var folderId = $('#global-doc-folder-select').val() || null;
                var tags = $('#global-doc-tags-input').val().trim();
                GlobalDocsManager.upload(file, displayName, folderId, tags);
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

            GlobalDocsManager.upload(fileOrUrl, displayName, $('#global-doc-folder-select').val() || null, $('#global-doc-tags-input').val().trim());
        });

        // Refresh button
        $('#global-doc-refresh-btn').off('click').on('click', function () {
            GlobalDocsManager.refresh();
        });

        // View switcher — Folders view directly opens the file browser
        $('#global-docs-view-switcher').on('click', 'button[data-view]', function() {
            var view = $(this).data('view');
            GlobalDocsManager._viewMode = view;
            localStorage.setItem('globalDocsViewMode', view);
            $('#global-docs-view-switcher button').removeClass('active');
            $(this).addClass('active');
            if (view === 'list') {
                $('#global-docs-view-list').show();
                $('#global-docs-view-folder').hide();
                $('#global-docs-dialog').removeClass('modal-xl').addClass('modal-lg');
            } else {
                $('#global-docs-view-list').hide();
                $('#global-docs-view-folder').show();
                $('#global-docs-dialog').removeClass('modal-lg').addClass('modal-xl');
                GlobalDocsManager._openFileBrowser();
            }
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
