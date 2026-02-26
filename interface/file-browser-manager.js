/**
 * File Browser Manager — Full-screen modal file browser & editor.
 *
 * Provides VS Code-like file tree navigation, CodeMirror 5 editing with syntax
 * highlighting, markdown preview, and full CRUD operations (create, rename, delete
 * files and folders). All file access is sandboxed to the server's working directory.
 *
 * Dependencies (all pre-loaded in interface.html):
 *   - jQuery + Bootstrap 4.6 (modal, dropdowns)
 *   - CodeMirror 5.65.16 (editor, modes: python, js, css, htmlmixed, xml, markdown, gfm)
 *   - marked.js (markdown preview, from common.js)
 *   - Bootstrap Icons (tree icons)
 *
 * @module FileBrowserManager
 */
/* global $, CodeMirror, showToast, marked, hljs, renderMarkdownToHtml */

var FileBrowserManager = (function () {
    'use strict';

    // ─── Mode map: file extension → CodeMirror mode (pre-loaded only) ───
    var MODE_MAP = {
        '.py':       'python',
        '.pyw':      'python',
        '.js':       'javascript',
        '.mjs':      'javascript',
        '.jsx':      'javascript',
        '.ts':       { name: 'javascript', typescript: true },
        '.tsx':      { name: 'javascript', typescript: true },
        '.json':     { name: 'javascript', json: true },
        '.html':     'htmlmixed',
        '.htm':      'htmlmixed',
        '.css':      'css',
        '.xml':      'xml',
        '.svg':      'xml',
        '.md':       'gfm',
        '.markdown': 'gfm'
    };

    // ─── File icon map: extension → Bootstrap Icon class ───
    var ICON_MAP = {
        '.py':   'bi-filetype-py',
        '.js':   'bi-filetype-js',
        '.ts':   'bi-filetype-tsx',
        '.tsx':  'bi-filetype-tsx',
        '.jsx':  'bi-filetype-jsx',
        '.json': 'bi-filetype-json',
        '.html': 'bi-filetype-html',
        '.htm':  'bi-filetype-html',
        '.css':  'bi-filetype-css',
        '.xml':  'bi-filetype-xml',
        '.md':   'bi-filetype-md',
        '.svg':  'bi-filetype-svg',
        '.yml':  'bi-filetype-yml',
        '.yaml': 'bi-filetype-yml',
        '.sh':   'bi-terminal',
        '.txt':  'bi-file-earmark-text'
    };


    // ─── Config (overridable via init(cfg) or configure(cfg)) ───
    var _config = {

        // ── Group 1: API Endpoints ─────────────────────────────────────────
        // All paths used by AJAX calls. Override individual keys or the whole object.
        // Set any value to null to disable that operation entirely.
        endpoints: {
            tree:     '/file-browser/tree',     // GET  ?path=
            read:     '/file-browser/read',     // GET  ?path=
            write:    '/file-browser/write',    // POST {path, content}
            mkdir:    '/file-browser/mkdir',    // POST {path}
            rename:   '/file-browser/rename',   // POST {old_path, new_path}
            delete:   '/file-browser/delete',   // POST {path, recursive}
            move:     '/file-browser/move',     // POST {src_path, dest_path}
            upload:   '/file-browser/upload',   // POST multipart {file, path}
            download: '/file-browser/download', // GET  ?path=
            serve:    '/file-browser/serve',    // GET  ?path=  (PDF inline)
            aiEdit:   '/file-browser/ai-edit'   // POST {path, instruction, ...}
        },

        // ── Group 2: DOM Element IDs ───────────────────────────────────────
        // IDs of elements that FileBrowserManager reads/writes/binds to.
        // For a second embedding, supply different IDs pointing to a second
        // set of elements (e.g. inside a different modal).
        dom: {
            // Main containers
            modal:              'file-browser-modal',
            openBtn:            'settings-file-browser-modal-open-button',
            tree:               'file-browser-tree',
            sidebar:            'file-browser-sidebar',
            addressBar:         'file-browser-address-bar',
            suggestionDropdown: 'file-browser-suggestion-dropdown',
            editorContainer:    'file-browser-editor-container',
            previewContainer:   'file-browser-preview-container',
            wysiwygContainer:   'file-browser-wysiwyg-container',
            pdfContainer:       'file-browser-pdf-container',
            emptyState:         'file-browser-empty-state',
            dirtyIndicator:     'file-browser-dirty-indicator',
            tabBar:             'file-browser-tab-bar',
            viewBtnGroup:       'fb-view-btngroup',
            viewSelect:         'file-browser-view-select',
            // Toolbar buttons
            saveBtn:            'file-browser-save-btn',
            discardBtn:         'file-browser-discard-btn',
            reloadBtn:          'file-browser-reload-btn',
            wrapBtn:            'file-browser-wrap-btn',
            downloadBtn:        'file-browser-download-btn',
            uploadBtn:          'file-browser-upload-btn',
            aiEditBtn:          'file-browser-ai-edit-btn',
            refreshBtn:         'file-browser-refresh-btn',
            newFileBtn:         'file-browser-new-file-btn',
            newFolderBtn:       'file-browser-new-folder-btn',
            sidebarToggle:      'file-browser-sidebar-toggle',
            closeBtn:           'file-browser-close-btn',
            themeSelect:        'file-browser-theme-select',
            // Context menu
            contextMenu:        'file-browser-context-menu',
            // Sub-modals
            confirmModal:       'file-browser-confirm-modal',
            confirmTitle:       'file-browser-confirm-title',
            confirmBody:        'file-browser-confirm-body',
            confirmOkBtn:       'file-browser-confirm-ok-btn',
            confirmCancelBtn:   'file-browser-confirm-cancel-btn',
            nameModal:          'file-browser-name-modal',
            nameTitle:          'file-browser-name-modal-title',
            nameHint:           'file-browser-name-modal-hint',
            nameDirHint:        'file-browser-name-modal-dir',
            nameOkBtn:          'file-browser-name-ok-btn',
            nameCancelBtn:      'file-browser-name-cancel-btn',
            nameInput:          'file-browser-name-input',
            moveModal:          'file-browser-move-modal',
            uploadModal:        'file-browser-upload-modal',
            aiEditModal:        'file-browser-ai-edit-modal',
            aiDiffModal:        'file-browser-ai-diff-modal',
            backdrop:           'file-browser-backdrop',
            loadAnywayBtn:      'file-browser-load-anyway-btn'
        },

        // ── Group 3: Behavior Flags ────────────────────────────────────────
        // All defaults reproduce current behavior.
        readOnly:        false,   // true = no write/create/rename/delete/upload
        allowUpload:     true,    // show/enable upload button
        allowDelete:     true,    // show/enable delete in context menu
        allowRename:     true,    // show/enable rename in context menu
        allowCreate:     true,    // show/enable new file + new folder buttons
        allowMove:       true,    // show/enable move in context menu + DnD
        allowAiEdit:     true,    // show/enable AI Edit button
        showEditor:      true,    // false = tree-only mode; editor panel hidden
        showAddressBar:  true,    // false = hide address bar

        // ── Group 4: Root & Title ──────────────────────────────────────────
        rootPath: '.',            // Directory to load when modal opens
        title:    'File Browser', // Text shown in modal header (future use)

        // ── Group 5: Operation Callbacks ──────────────────────────────────
        // Same contract as onMove: receive args + done(errorMsg|null).
        // Set to null to use default endpoint-based implementation.
        /**
         * Move a file/folder from srcPath to destPath.
         * Call done(null) on success, done(errorMessage) on failure.
         * Override this to use a different backend or move semantics.
         * @param {string} srcPath  - Source relative path.
         * @param {string} destPath - Full destination relative path (dir + basename).
         * @param {function} done   - Callback: done(errorMsg|null).
         */
        onMove: function (srcPath, destPath, done) {
            $.ajax({
                url: _config.endpoints.move,
                method: 'POST',
                contentType: 'application/json',
                data: JSON.stringify({ src_path: srcPath, dest_path: destPath }),
                success: function (r) {
                    done(r.status === 'success' ? null : (r.error || 'Move failed'));
                },
                error: function (xhr) {
                    var msg = 'Move failed';
                    try { msg = JSON.parse(xhr.responseText).error || msg; } catch (ex) {}
                    done(msg);
                }
            });
        },
        onDelete: null,        // function(path, done)
        onRename: null,        // function(oldPath, newPath, done)
        onCreateFolder: null,  // function(path, done)
        onCreateFile: null,    // function(path, done)
        onUpload: null,        // function(file, targetDir, done)
        onSave: null,          // function(path, content, done)

        // ── Group 6: Selection / Lifecycle Events ─────────────────────────
        // Pure notification callbacks — no done() needed.
        onSelect: null,        // function(path, type, entry)
        onOpen:   null,        // function()
        onClose:  null,        // function()

        // ── Group 7: Custom Rendering ──────────────────────────────────────
        enrichEntry: null,     // function(entry, path, done) — async enrichment
        renderEntry: null,     // function(entry, path) — return jQuery element or null
        buildContextMenu: null // function(path, type) — return [{label,icon,action}] or null
    };

    /** Resolve a config DOM key to a jQuery wrapped element. */
    function _$(key) { return $('#' + (_config.dom[key] || key)); }

    /** Resolve a config endpoint name to its URL string, or null if disabled. */
    function _ep(name) { return (_config.endpoints && _config.endpoints[name]) || null; }

    // ─── State ───
    var state = {
        currentPath: null,        // Currently open file path (relative to server root)
        currentDir: '.',          // Currently viewed directory in address bar
        originalContent: '',      // Content as loaded from server (for discard)
        isDirty: false,           // Has unsaved changes
        cmEditor: null,           // CodeMirror 5 instance
        sidebarVisible: true,     // Sidebar collapse state
        expandedDirs: {},         // Map of expanded directory paths → true
        isMarkdown: false,        // Current file is .md / .markdown
        activeTab: 'code',        // 'code' or 'preview' (for markdown)
        contextTarget: null,      // Tree item that was right-clicked (for context menu)
        currentTheme: 'monokai',  // Current CodeMirror theme
        initialized: false,
        pathSuggestions: [],
        pathSuggestionMap: {},
        aiEditSelection: null,      // {from, to} CodeMirror cursor positions
        aiEditProposed: null,       // LLM's replacement text
        aiEditOriginal: null,       // Original text (selection or full file)
        aiEditIsSelection: false,   // Whether editing a selection vs whole file
        aiEditStartLine: null,      // 1-indexed start line
        aiEditEndLine: null,        // 1-indexed end line
        aiEditBaseHash: null,        // Hash from server response
        aiEditLastDiffText: null,    // Most-recent diff text (for Edit Instruction context)
        wordWrap: false,              // Whether line wrapping is enabled in the editor
        isPdf: false,                  // Whether current file is a PDF
        pdfBlobUrl: null,              // Current PDF blob URL (for memory cleanup)
        viewMode: 'raw',              // 'raw' | 'preview' | 'wysiwyg' (for markdown files)
        fbEasyMDE: null,               // EasyMDE instance (lazy-created, persisted)
        dragSource: null,              // {path,type,name} of tree item currently being dragged
        moveTarget: null,              // {path,type,name} of item being moved via context menu
        moveDest: null                 // Destination dir selected in move modal
    };

    // ═══════════════════════════════════════════════════════════════
    //  Utility helpers
    // ═══════════════════════════════════════════════════════════════

    /**
     * Get file extension from a path (lowercase, including the dot).
     * @param {string} filePath - File path or name.
     * @returns {string} Extension like '.py' or '' if none.
     */
    function _ext(filePath) {
        var dot = filePath.lastIndexOf('.');
        if (dot < 1) return '';
        return filePath.substring(dot).toLowerCase();
    }

    /**
     * Get the parent directory of a path (relative).
     * @param {string} p - Relative path.
     * @returns {string} Parent directory path, or '.' for root-level items.
     */
    function _parentDir(p) {
        if (!p || p === '.') return '.';
        var parts = p.replace(/\\/g, '/').split('/');
        parts.pop();
        return parts.length === 0 ? '.' : parts.join('/');
    }

    /**
     * Get just the filename from a path.
     * @param {string} p - Relative path.
     * @returns {string} Filename component.
     */
    function _basename(p) {
        if (!p) return '';
        var parts = p.replace(/\\/g, '/').split('/');
        return parts[parts.length - 1] || '';
    }

    /**
     * Build a relative path by joining a directory and a name.
     * @param {string} dir - Directory path.
     * @param {string} name - Filename or subdirectory name.
     * @returns {string} Combined relative path.
     */
    function _joinPath(dir, name) {
        if (!dir || dir === '.') return name;
        return dir.replace(/\/+$/, '') + '/' + name;
    }

    /**
     * Get a Bootstrap Icon class for a file based on its extension.
     * @param {string} name - File name or path.
     * @param {string} type - 'file' or 'dir'.
     * @param {boolean} [expanded] - Whether the directory is expanded.
     * @returns {string} Full icon class name.
     */
    function _icon(name, type, expanded) {
        if (type === 'dir') {
            return expanded ? 'bi bi-folder2-open text-warning' : 'bi bi-folder-fill text-warning';
        }
        var ext = _ext(name);
        return 'bi ' + (ICON_MAP[ext] || 'bi-file-earmark');
    }

    /**
     * Determine if a file extension indicates a markdown file.
     * @param {string} ext - File extension (e.g. '.md').
     * @returns {boolean}
     */
    function _isMarkdownExt(ext) {
        return ext === '.md' || ext === '.markdown';
    }

    /**
     * Update the dirty indicator and save/discard button states.
     */
    function _updateDirtyState() {
        if (state.isDirty) {
            _$('dirtyIndicator').addClass('visible');
            _$('saveBtn').prop('disabled', false);
            _$('discardBtn').show();
        } else {
            _$('dirtyIndicator').removeClass('visible');
            _$('saveBtn').prop('disabled', true);
            _$('discardBtn').hide();
        }
    }

    /**
     * Show a specific view in the editor area: 'editor', 'preview', 'empty', or 'message'.
     * @param {string} view - One of 'editor', 'preview', 'empty', 'message'.
     * @param {string} [messageHtml] - HTML content for the 'message' view.
     */
    function _showView(view, messageHtml) {
        var edEl = document.getElementById(_config.dom.editorContainer);
        var prEl = document.getElementById(_config.dom.previewContainer);
        var wyEl = document.getElementById(_config.dom.wysiwygContainer);
        var pdEl = document.getElementById(_config.dom.pdfContainer);
        var emEl = document.getElementById(_config.dom.emptyState);
        if (!edEl || !prEl || !emEl) return;
        edEl.style.display = (view === 'editor')  ? 'block' : 'none';
        prEl.style.display = (view === 'preview') ? 'block' : 'none';
        if (wyEl) wyEl.style.display = (view === 'wysiwyg') ? 'flex'  : 'none';
        if (pdEl) pdEl.style.display = (view === 'pdf')     ? 'flex'  : 'none';
        emEl.style.display = (view === 'empty' || view === 'message') ? 'flex' : 'none';
        if (view === 'message' && messageHtml) {
            emEl.innerHTML = '<div class="text-center text-muted">' + messageHtml + '</div>';
        } else if (view === 'empty') {
            emEl.innerHTML =
                '<div class="text-center text-muted">' +
                '<i class="bi bi-folder2-open" style="font-size: 3rem;"></i>' +
                '<p class="mt-2">Select a file from the tree to edit</p></div>';
        }
        if (view === 'editor' && state.cmEditor) {
            setTimeout(function () { state.cmEditor.refresh(); }, 10);
        }
    }

    /**
     * Load a PDF file using PDF.js iframe viewer.
     * Scoped version of showPDF() from common.js — all element lookups are
     * scoped to #file-browser-pdf-container to avoid conflicts with the chat UI.
     * @param {string} filePath - Relative path to the PDF file.
     */
    function _loadFilePDF(filePath) {
        var progressWrap = document.getElementById('fb-pdf-progress');
        var progressBar  = document.getElementById('fb-pdf-progressbar');
        var progressStatus = document.getElementById('fb-pdf-progress-status');
        var viewer = document.getElementById('fb-pdfjs-viewer');
        if (!progressWrap || !viewer) return;

        // Reset UI
        progressBar.style.width = '0%';
        progressStatus.textContent = '';
        viewer.style.display = 'none';
        progressWrap.style.display = 'block';

        // Revoke previous blob URL to free memory
        if (state.pdfBlobUrl) {
            URL.revokeObjectURL(state.pdfBlobUrl);
            state.pdfBlobUrl = null;
        }

        var xhr = new XMLHttpRequest();
        xhr.open('GET', _ep('serve') + '?path=' + encodeURIComponent(filePath), true);
        xhr.responseType = 'blob';

        xhr.onprogress = function (e) {
            if (e.lengthComputable) {
                var pct = (e.loaded / e.total) * 100;
                progressBar.style.width = pct + '%';
                progressStatus.textContent = 'Downloaded ' + (e.loaded / 1024).toFixed(1) + ' / ' + (e.total / 1024).toFixed(1) + ' KB (' + Math.round(pct) + '%)';
            } else {
                progressStatus.textContent = 'Downloaded ' + (e.loaded / 1024).toFixed(1) + ' KB';
            }
        };

        xhr.onload = function () {
            progressWrap.style.display = 'none';
            if (this.status === 200) {
                state.pdfBlobUrl = URL.createObjectURL(this.response);
                var originalSrc = viewer.getAttribute('data-original-src');
                viewer.setAttribute('src', originalSrc + '?file=' + encodeURIComponent(state.pdfBlobUrl));
                viewer.style.display = 'block';
            } else {
                _showView('message',
                    '<i class="bi bi-exclamation-triangle" style="font-size:2rem; color:#ffc107;"></i>' +
                    '<p class="mt-2">Failed to load PDF (HTTP ' + this.status + ')</p>'
                );
            }
        };

        xhr.onerror = function () {
            progressWrap.style.display = 'none';
            _showView('message',
                '<i class="bi bi-exclamation-triangle" style="font-size:2rem; color:#ffc107;"></i>' +
                '<p class="mt-2">Network error loading PDF</p>'
            );
        };

        xhr.send();
    }

    /**
     * Update toolbar button enabled/disabled state based on current file type and view mode.
     * Called after every file load and view mode switch.
     */
    function _updateToolbarForFileType() {
        var isPdf = state.isPdf;
        var isWysiwyg = (state.viewMode === 'wysiwyg');

        _$('saveBtn').prop('disabled', isPdf);
        _$('discardBtn').prop('disabled', isPdf);
        _$('aiEditBtn').prop('disabled', isPdf || isWysiwyg);
        _$('wrapBtn').prop('disabled', isPdf || isWysiwyg);
        _$('reloadBtn').prop('disabled', isPdf);
        if (!isPdf) {
            _$('downloadBtn').prop('disabled', false);
        }
    }

    /**
     * Set the active view mode (raw | preview | wysiwyg) for the current file.
     * Syncs EasyMDE → CodeMirror before leaving WYSIWYG mode.
     * @param {string} mode - 'raw', 'preview', or 'wysiwyg'.
     */
    function _setViewMode(mode) {
        // Sync WYSIWYG content back to CodeMirror before leaving
        if (state.viewMode === 'wysiwyg' && mode !== 'wysiwyg') {
            _syncWysiwygToCodeMirror();
        }

        state.viewMode = mode;

        // Update button group active state
        _$('viewBtnGroup').find('.btn').removeClass('active');
        _$('viewBtnGroup').find('.btn[data-view="' + mode + '"]').addClass('active');
        // Update select value
        _$('viewSelect').val(mode);

        if (mode === 'raw') {
            _showView('editor');
            setTimeout(function () { if (state.cmEditor) state.cmEditor.refresh(); }, 10);
        } else if (mode === 'preview') {
            _renderPreview();
            _showView('preview');
        } else if (mode === 'wysiwyg') {
            _showView('wysiwyg');
            _initOrRefreshEasyMDE();
        }

        _updateToolbarForFileType();
    }

    /**
     * Initialize the EasyMDE WYSIWYG editor instance lazily, or refresh it with current content.
     * Creates EasyMDE inside #file-browser-wysiwyg-container on first call.
     * On subsequent calls, just updates the content.
     */
    function _initOrRefreshEasyMDE() {
        var content = state.cmEditor ? state.cmEditor.getValue() : '';
        var container = document.getElementById(_config.dom.wysiwygContainer);
        if (!container) return;

        if (!state.fbEasyMDE) {
            // Create a textarea for EasyMDE to attach to
            var ta = document.createElement('textarea');
            ta.id = 'fb-easymde-textarea';
            container.appendChild(ta);

            state.fbEasyMDE = new EasyMDE({
                element: ta,
                spellChecker: false,
                autofocus: false,
                status: false,
                minHeight: '300px',
                toolbar: [
                    'bold', 'italic', 'heading', '|',
                    'quote', 'code', 'unordered-list', 'ordered-list', '|',
                    'link', 'image', 'table', '|',
                    'undo', 'redo'
                ],
                previewRender: function (plainText) {
                    if (typeof marked !== 'undefined') {
                        return marked.parse ? marked.parse(plainText) : marked(plainText);
                    }
                    return plainText;
                },
                shortcuts: {
                    // Prevent EasyMDE intercepting Ctrl-S so our global save handler fires
                    toggleSideBySide: null,
                    toggleFullScreen: null
                }
            });

            // Dirty tracking — EasyMDE changes mark the file as dirty
            state.fbEasyMDE.codemirror.on('change', function () {
                if (state.currentPath && !state.isDirty) {
                    state.isDirty = true;
                    _updateDirtyState();
                }
            });
        }

        state.fbEasyMDE.value(content);
        setTimeout(function () {
            state.fbEasyMDE.codemirror.refresh();
        }, 50);
    }

    /**
     * Sync EasyMDE content back into CodeMirror (source of truth).
     * Called before save, file navigation, or switching away from WYSIWYG mode.
     */
    function _syncWysiwygToCodeMirror() {
        if (state.fbEasyMDE && state.cmEditor) {
            var content = state.fbEasyMDE.value();
            state.cmEditor.setValue(content);
        }
    }

    /**
     * Ensure the CodeMirror editor instance exists.
     * Creates it lazily on first call to avoid rendering in a hidden container.
     */
    function _ensureEditor() {
        if (state.cmEditor) return;
        state.cmEditor = CodeMirror(_$('editorContainer')[0], {
            lineNumbers: true,
            theme: state.currentTheme,
            mode: null,
            autoCloseBrackets: true,
            matchBrackets: true,
            styleActiveLine: true,
            foldGutter: true,
            gutters: ['CodeMirror-linenumbers', 'CodeMirror-foldgutter'],
            indentUnit: 4,
            tabSize: 4,
            indentWithTabs: false,
            lineWrapping: false,
            extraKeys: {
                'Tab': function (cm) {
                    if (cm.somethingSelected()) {
                        cm.indentSelection('add');
                    } else {
                        cm.replaceSelection('    ', 'end');
                    }
                },
                'Cmd-K': function(cm) { if (state.viewMode !== 'wysiwyg') _showAiEditModal(); },
                'Ctrl-K': function(cm) { if (state.viewMode !== 'wysiwyg') _showAiEditModal(); }
            }
        });
        state.cmEditor.on('change', function () {
            if (!state.currentPath) return;
            var newDirty = (state.cmEditor.getValue() !== state.originalContent);
            if (newDirty !== state.isDirty) {
                state.isDirty = newDirty;
                _updateDirtyState();
            }
        });
    }

    /**
     * Toggle word wrap on the CodeMirror editor.
     * Updates state.wordWrap and the active style of the wrap button.
     */
    function _toggleWordWrap() {
        if (!state.cmEditor) return;
        state.wordWrap = !state.wordWrap;
        state.cmEditor.setOption('lineWrapping', state.wordWrap);
        _$('wrapBtn').toggleClass('active', state.wordWrap);
    }

    /**
     * Check for unsaved changes and prompt user if dirty.
     * @returns {boolean} true if safe to proceed, false if user cancelled.
     */
    /**
     * If the editor has unsaved changes, show a confirmation dialog.
     * Calls onProceed() when user confirms (or if not dirty).
     * @param {function} onProceed - Called when safe to proceed.
     */
    function _confirmIfDirty(onProceed) {
        if (!state.isDirty) { onProceed(); return; }
        _showConfirmModal('Unsaved Changes', 'You have unsaved changes. Discard them?', function () {
            onProceed();
        }, { okText: 'Discard', okClass: 'btn-warning' });
    }

    // ═══════════════════════════════════════════════════════════════
    //  Tree rendering
    // ═══════════════════════════════════════════════════════════════

    /**
     * Load and render a directory listing in the file tree sidebar.
     * @param {string} dirPath - Relative directory path to load.
     * @param {jQuery} [$parentUl] - Parent <ul> element to append children to.
     *                               If null, replaces the entire tree.
     */
    function loadTree(dirPath, $parentUl) {
        $.getJSON(_ep('tree'), { path: dirPath })
            .done(function (resp) {
                if (resp.status !== 'success') {
                    showToast('Failed to load tree: ' + (resp.error || 'Unknown'), 'error');
                    return;
                }
                var entries = resp.entries || [];
                var $ul = $('<ul></ul>');

                entries.forEach(function (entry) {
                    var entryPath = _joinPath(dirPath, entry.name);
                    var isDir = (entry.type === 'dir');
                    var isExpanded = !!state.expandedDirs[entryPath];
                    var iconClass = _icon(entry.name, entry.type, isExpanded);

                    var $li = $('<li></li>')
                        .attr('data-path', entryPath)
                        .attr('data-type', entry.type)
                        .attr('data-name', entry.name)
                        .attr('draggable', 'true');

                    var $iconSpan = $('<span class="tree-icon"><i class="' + iconClass + '"></i></span>');
                    var $nameSpan = $('<span class="tree-name"></span>').text(entry.name);
                    $li.append($iconSpan).append($nameSpan);
                    $li.data('entry', entry);

                    // Custom rendering hook (sync)
                    if (_config.renderEntry) {
                        var $custom = _config.renderEntry(entry, entryPath);
                        if ($custom) {
                            $li.empty().append($custom.contents ? $custom.contents() : $custom);
                        }
                    }

                    // Highlight currently open file
                    if (!isDir && state.currentPath === entryPath) {
                        $li.addClass('active');
                    }

                    $ul.append($li);

                    // If directory was previously expanded, re-expand it
                    if (isDir && isExpanded) {
                        loadTree(entryPath, $ul);
                    }
                });

                // Async enrichment hook (post-render)
                if (_config.enrichEntry) {
                    $ul.find('> li').each(function() {
                        var $li = $(this);
                        var entry = $li.data('entry');
                        if (!entry) return;
                        _config.enrichEntry(entry, $li.attr('data-path'), function(enriched) {
                            $li.data('entry', enriched);
                            if (_config.renderEntry) {
                                var $custom = _config.renderEntry(enriched, $li.attr('data-path'));
                                if ($custom) {
                                    $li.empty().append($custom.contents ? $custom.contents() : $custom);
                                }
                            }
                        });
                    });
                }

                if ($parentUl) {
                    // Appending as a child of a directory <li>
                    var $parentLi = $parentUl.children('li[data-path="' + CSS.escape(dirPath) + '"]');
                    if ($parentLi.length) {
                        $parentLi.find('> ul').remove();
                        $parentLi.append($ul);
                    } else {
                        $parentUl.append($ul);
                    }
                } else {
                    // Root level: replace entire tree content
                    _$('tree').empty().append($ul);
                }
                _refreshPathSuggestions();
            })
            .fail(function (xhr) {
                var msg = 'Failed to load directory';
                try { msg = JSON.parse(xhr.responseText).error || msg; } catch (e) { /* ignore */ }
                showToast(msg, 'error');
            });
    }

    /**
     * Rebuild the list of all known file/directory paths from the tree.
     * Called after tree refresh. Stores sorted paths for fuzzy autocomplete.
     */
    function _refreshPathSuggestions() {
        var paths = [];
        _$('tree').find('li').each(function () {
            var p = $(this).attr('data-path');
            if (p) paths.push(p);
        });
        paths.sort();
        state.pathSuggestions = paths;
        state.pathSuggestionMap = {};
        paths.forEach(function (p) {
            state.pathSuggestionMap[p] = true;
        });
    }

    // ═══════════════════════════════════════════════════════════════
    //  Fuzzy matching for address bar autocomplete
    // ═══════════════════════════════════════════════════════════════

    /**
     * Fuzzy-match a query against a target string.
     * All query characters must appear in order in the target (case-insensitive).
     * Returns { score, indexes } or null if no match.
     * Scoring: consecutive matches > word-boundary matches > mid-word.
     * @param {string} needle - The search query.
     * @param {string} haystack - The target string to match against.
     * @returns {object|null} { score: number, indexes: number[] } or null.
     */
    function _fuzzyMatch(needle, haystack) {
        var nLower = needle.toLowerCase();
        var hLower = haystack.toLowerCase();
        var nLen = nLower.length;
        var hLen = hLower.length;

        if (nLen === 0) return { score: 0, indexes: [] };
        if (nLen > hLen) return null;

        // Quick substring check — best case
        var subIdx = hLower.indexOf(nLower);
        if (subIdx !== -1) {
            var idxs = [];
            for (var si = 0; si < nLen; si++) idxs.push(subIdx + si);
            // Bonus: substring at start of word boundary scores higher
            var bonus = 1.5;
            if (subIdx === 0) bonus = 2.0;
            else if ('/\\-_. '.indexOf(hLower[subIdx - 1]) !== -1) bonus = 1.8;
            return { score: nLen * bonus + (1 / (subIdx + 1)), indexes: idxs };
        }

        // Sequential char matching with scoring
        var indexes = [];
        var score = 0;
        var hIdx = 0;
        var lastMatchIdx = -2;

        for (var ni = 0; ni < nLen; ni++) {
            var found = false;
            for (var hi = hIdx; hi < hLen; hi++) {
                if (hLower[hi] === nLower[ni]) {
                    indexes.push(hi);
                    // Score this position
                    if (hi === lastMatchIdx + 1) {
                        // Consecutive match
                        score += 1.0;
                    } else if (hi === 0 || '/\\-_. '.indexOf(hLower[hi - 1]) !== -1) {
                        // Word boundary match
                        score += 0.8;
                    } else {
                        // Mid-word match
                        score += 0.3;
                        // Penalty for gap
                        score -= (hi - lastMatchIdx - 1) * 0.005;
                    }
                    lastMatchIdx = hi;
                    hIdx = hi + 1;
                    found = true;
                    break;
                }
            }
            if (!found) return null;
        }

        // Small penalty for longer targets (prefer concise matches)
        score -= (hLen - nLen) * 0.01;
        return { score: score, indexes: indexes };
    }

    /**
     * Fuzzy-match a query against a file path, boosting filename matches.
     * Tries matching against the filename component first (1.5x boost),
     * then falls back to full path matching.
     * @param {string} query - The search query.
     * @param {string} path - The full file path.
     * @returns {object|null} { score, indexes, path } or null.
     */
    function _fuzzyMatchPath(query, path) {
        var lastSlash = path.lastIndexOf('/');
        var filename = lastSlash >= 0 ? path.substring(lastSlash + 1) : path;

        // Try filename first (boosted)
        var fnMatch = _fuzzyMatch(query, filename);
        if (fnMatch && fnMatch.score > 0) {
            var offset = lastSlash + 1;
            var adjustedIndexes = [];
            for (var i = 0; i < fnMatch.indexes.length; i++) {
                adjustedIndexes.push(fnMatch.indexes[i] + offset);
            }
            return { score: fnMatch.score * 1.5, indexes: adjustedIndexes, path: path };
        }

        // Fallback: match against full path
        var fullMatch = _fuzzyMatch(query, path);
        if (fullMatch) {
            return { score: fullMatch.score, indexes: fullMatch.indexes, path: path };
        }
        return null;
    }

    /**
     * HTML-escape a string for safe insertion into the DOM.
     * @param {string} str - Raw string.
     * @returns {string} Escaped string.
     */
    function _escHtml(str) {
        return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }

    /**
     * Render a file path with matched character positions highlighted.
     * Splits into directory part and filename part for separate styling.
     * @param {string} path - The full file path.
     * @param {number[]} indexes - Matched character indexes to highlight.
     * @returns {string} HTML string with matched chars wrapped in <b class="fb-match-char">.
     */
    function _renderHighlightedPath(path, indexes) {
        var indexSet = {};
        for (var k = 0; k < indexes.length; k++) indexSet[indexes[k]] = true;

        var lastSlash = path.lastIndexOf('/');
        var dir = lastSlash >= 0 ? path.substring(0, lastSlash + 1) : '';
        var filename = lastSlash >= 0 ? path.substring(lastSlash + 1) : path;

        var html = '';
        // Directory part (muted)
        if (dir) {
            html += '<span class="fb-match-dir">';
            for (var d = 0; d < dir.length; d++) {
                var ch = _escHtml(dir[d]);
                if (indexSet[d]) html += '<b class="fb-match-char">' + ch + '</b>';
                else html += ch;
            }
            html += '</span>';
        }
        // Filename part (prominent)
        html += '<span class="fb-match-filename">';
        for (var f = 0; f < filename.length; f++) {
            var idx = (lastSlash >= 0 ? lastSlash + 1 : 0) + f;
            var fc = _escHtml(filename[f]);
            if (indexSet[idx]) html += '<b class="fb-match-char">' + fc + '</b>';
            else html += fc;
        }
        html += '</span>';
        return html;
    }

    /** Index of the currently highlighted suggestion in the dropdown (-1 = none). */
    var _suggestionActiveIdx = -1;

    /**
     * Filter paths by fuzzy query and render the suggestion dropdown.
     * Called on every keystroke in the address bar.
     * @param {string} query - Current input value.
     */
    function _filterAndShowSuggestions(query) {
        var $dropdown = _$('suggestionDropdown');
        if (!query || query.length === 0) {
            $dropdown.hide().empty();
            _suggestionActiveIdx = -1;
            return;
        }

        var results = [];
        for (var i = 0; i < state.pathSuggestions.length; i++) {
            var m = _fuzzyMatchPath(query, state.pathSuggestions[i]);
            if (m) results.push(m);
        }

        // Sort by score descending
        results.sort(function(a, b) { return b.score - a.score; });

        // Limit to top 30
        if (results.length > 30) results = results.slice(0, 30);

        if (results.length === 0) {
            $dropdown.hide().empty();
            _suggestionActiveIdx = -1;
            return;
        }

        var html = '';
        for (var r = 0; r < results.length; r++) {
            html += '<div class="fb-suggestion-item" data-path="' +
                _escHtml(results[r].path) + '">' +
                _renderHighlightedPath(results[r].path, results[r].indexes) +
                '</div>';
        }
        $dropdown.html(html).show();
        _suggestionActiveIdx = -1;
    }

    /**
     * Hide the suggestion dropdown and reset active index.
     */
    function _hideSuggestionDropdown() {
        _$('suggestionDropdown').hide().empty();
        _suggestionActiveIdx = -1;
    }

    /**
     * Navigate the suggestion dropdown with arrow keys and select with Enter.
     * @param {string} key - 'ArrowDown', 'ArrowUp', or 'Enter'.
     * @returns {boolean} true if the key was handled, false otherwise.
     */
    function _handleSuggestionNav(key) {
        var $dropdown = _$('suggestionDropdown');
        if ($dropdown.css('display') === 'none') return false;
        var $items = $dropdown.find('.fb-suggestion-item');
        if ($items.length === 0) return false;

        if (key === 'ArrowDown') {
            _suggestionActiveIdx = Math.min(_suggestionActiveIdx + 1, $items.length - 1);
            $items.removeClass('active');
            $($items[_suggestionActiveIdx]).addClass('active');
            // Scroll into view
            var el = $items[_suggestionActiveIdx];
            if (el) el.scrollIntoView({ block: 'nearest' });
            return true;
        }
        if (key === 'ArrowUp') {
            _suggestionActiveIdx = Math.max(_suggestionActiveIdx - 1, 0);
            $items.removeClass('active');
            $($items[_suggestionActiveIdx]).addClass('active');
            var elUp = $items[_suggestionActiveIdx];
            if (elUp) elUp.scrollIntoView({ block: 'nearest' });
            return true;
        }
        if (key === 'Enter' && _suggestionActiveIdx >= 0 && _suggestionActiveIdx < $items.length) {
            var selectedPath = $($items[_suggestionActiveIdx]).attr('data-path');
            if (selectedPath) {
                _$('addressBar').val(selectedPath);
                _hideSuggestionDropdown();
                _navigateAddressBar(selectedPath);
            }
            return true;
        }
        return false;
    }

    /**
     * Toggle expansion of a directory node in the tree.
     * @param {jQuery} $li - The <li> element for the directory.
     */
    function _toggleDir($li) {
        var dirPath = $li.attr('data-path');
        if (state.expandedDirs[dirPath]) {
            // Collapse
            delete state.expandedDirs[dirPath];
            $li.find('> ul').remove();
            $li.find('> .tree-icon i').attr('class', _icon($li.attr('data-name'), 'dir', false));
        } else {
            // Expand
            state.expandedDirs[dirPath] = true;
            $li.find('> .tree-icon i').attr('class', _icon($li.attr('data-name'), 'dir', true));
            var $childUl = $('<ul></ul>');
            $li.append($childUl);
            loadTree(dirPath, $li.parent());
        }
        // Update address bar to show this directory
        state.currentDir = dirPath;
        if (!state.currentPath) {
            _$('addressBar').val(dirPath === '.' ? '' : dirPath);
        }
    }

    /**
     * Highlight the currently open file in the tree and remove previous highlight.
     * @param {string} filePath - Relative file path to highlight.
     */
    function _highlightTreeItem(filePath) {
        _$('tree').find('li.active').removeClass('active');
        if (filePath) {
            _$('tree').find('li[data-path="' + CSS.escape(filePath) + '"]').addClass('active');
        }
    }

    // ═══════════════════════════════════════════════════════════════
    //  File loading & editing
    // ═══════════════════════════════════════════════════════════════

    /**
     * Load a file from the server into the editor.
     * Checks for unsaved changes before navigating.
     * @param {string} filePath - Relative path to the file.
     * @param {boolean} [force] - If true, skip the 2MB size guard.
     */
    function loadFile(filePath, force) {
        _confirmIfDirty(function () { _doLoadFile(filePath, force); });
    }

    /**
     * Internal: perform the actual file loading (after dirty check passed).
     */
    function _doLoadFile(filePath, force) {
        var params = { path: filePath };
        if (force) params.force = 'true';

        // Clean up any previous PDF blob URL
        if (state.pdfBlobUrl) {
            URL.revokeObjectURL(state.pdfBlobUrl);
            state.pdfBlobUrl = null;
        }
        // Clear EasyMDE stale content
        if (state.fbEasyMDE) {
            state.fbEasyMDE.value('');
        }

        $.getJSON(_ep('read'), params)
            .done(function (resp) {
                if (resp.status !== 'success') {
                    showToast('Failed to read file: ' + (resp.error || 'Unknown'), 'error');
                    return;
                }

                // Handle binary files
                if (resp.is_binary) {
                    state.currentPath = filePath;
                    state.originalContent = '';
                    state.isDirty = false;
                    state.isMarkdown = false;
                    _updateDirtyState();
                    _highlightTreeItem(filePath);
                    _$('addressBar').val(filePath);
                    _$('tabBar').hide();
                    _showView('message',
                        '<i class="bi bi-file-earmark-binary" style="font-size: 3rem;"></i>' +
                        '<p class="mt-2">Binary file — cannot edit</p>' +
                        '<small class="text-muted">' + _basename(filePath) + ' (' + _formatSize(resp.size) + ')</small>'
                    );
                    _$('aiEditBtn').prop('disabled', true);
                    _$('reloadBtn').prop('disabled', true);
                    _$('wrapBtn').prop('disabled', true);
                    _$('downloadBtn').prop('disabled', true);
                    return;
                }

                // Handle too-large files
                if (resp.too_large) {
                    state.currentPath = filePath;
                    state.originalContent = '';
                    state.isDirty = false;
                    state.isMarkdown = false;
                    _updateDirtyState();
                    _highlightTreeItem(filePath);
                    _$('addressBar').val(filePath);
                    _$('tabBar').hide();
                    _showView('message',
                        '<i class="bi bi-exclamation-triangle" style="font-size: 3rem; color: #ffc107;"></i>' +
                        '<p class="mt-2">File is too large (' + _formatSize(resp.size) + ')</p>' +
                        '<button class="btn btn-sm btn-outline-warning" id="file-browser-load-anyway-btn">Load Anyway</button>'
                    );
                    // Bind the Load Anyway button
                    _$('loadAnywayBtn').off('click').on('click', function () {
                        loadFile(filePath, true);
                    });
                    _$('aiEditBtn').prop('disabled', true);
                    _$('reloadBtn').prop('disabled', true);
                    _$('wrapBtn').prop('disabled', true);
                    _$('downloadBtn').prop('disabled', true);
                    return;
                }

                // PDF files — render with PDF.js viewer instead of CodeMirror
                var extCheck = _ext(filePath);
                if (extCheck === '.pdf') {
                    state.currentPath = filePath;
                    state.currentDir = _parentDir(filePath);
                    state.isPdf = true;
                    state.isMarkdown = false;
                    state.viewMode = 'raw';
                    state.isDirty = false;
                    state.originalContent = '';
                    _updateDirtyState();
                    _highlightTreeItem(filePath);
                    _$('addressBar').val(filePath);
                    _$('tabBar').hide();
                    _$('downloadBtn').prop('disabled', false);
                    _$('reloadBtn').prop('disabled', true);
                    _updateToolbarForFileType();
                    _showView('pdf');
                    _loadFilePDF(filePath);
                    return;
                }
                state.isPdf = false;

                // Normal file — load into editor
                _ensureEditor();
                var ext = _ext(filePath);
                var mode = MODE_MAP[ext] || null;

                state.currentPath = filePath;
                state.currentDir = _parentDir(filePath);
                state.originalContent = resp.content;
                state.isDirty = false;
                state.isMarkdown = _isMarkdownExt(ext);
                state.activeTab = 'code';

                state.cmEditor.setValue(resp.content);
                state.cmEditor.setOption('mode', mode);
                state.cmEditor.clearHistory();

                _updateDirtyState();
                _highlightTreeItem(filePath);
                _$('addressBar').val(filePath);

                // View mode selector — shown only for markdown files; reset to Raw
                state.viewMode = 'raw';
                if (state.isMarkdown) {
                    _$('viewBtnGroup').find('.btn').removeClass('active');
                    $('#fb-view-btngroup .btn[data-view="raw"]').addClass('active');
                    _$('viewSelect').val('raw');
                    if (state.sidebarVisible) { _$('tabBar').show(); }
                } else {
                    _$('tabBar').hide();
                }

                _showView('editor');
                _updateToolbarForFileType();
                // Move cursor to top
                state.cmEditor.setCursor(0, 0);
                state.cmEditor.focus();
                _$('aiEditBtn').prop('disabled', false);
                _$('reloadBtn').prop('disabled', false);
                _$('wrapBtn').prop('disabled', false);
                _$('downloadBtn').prop('disabled', false);
            })
            .fail(function (xhr) {
                var msg = 'Failed to read file';
                try { msg = JSON.parse(xhr.responseText).error || msg; } catch (e) { /* ignore */ }
                showToast(msg, 'error');
            });
    }

    /**
     * Format a file size in bytes to a human-readable string.
     * @param {number} bytes - File size in bytes.
     * @returns {string} Formatted size string.
     */
    function _formatSize(bytes) {
        if (bytes < 1024) return bytes + ' B';
        if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
        return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
    }

    /**
     * Save the current file to the server.
     */
    function saveFile() {
        if (_config.readOnly) return;
        // Sync WYSIWYG content to CodeMirror before reading for save
        if (state.viewMode === 'wysiwyg') {
            _syncWysiwygToCodeMirror();
        }
        if (!state.currentPath || !state.isDirty) return;

        var content = state.cmEditor.getValue();
        var done = function(err) {
            if (err) { showToast('Save failed: ' + err, 'error'); return; }
            state.originalContent = content;
            state.isDirty = false;
            _updateDirtyState();
            showToast('Saved: ' + _basename(state.currentPath), 'success');
        };
        if (_config.onSave) {
            _config.onSave(state.currentPath, content, done);
        } else {
            if (!_ep('write')) { done('Not supported'); return; }
            $.ajax({
                url: _ep('write'),
                method: 'POST',
                contentType: 'application/json',
                data: JSON.stringify({ path: state.currentPath, content: content })
            })
            .done(function (resp) {
                if (resp.status === 'success') {
                    done(null);
                } else {
                    done(resp.error || 'Unknown');
                }
            })
            .fail(function (xhr) {
                var msg = 'Save failed';
                try { msg = JSON.parse(xhr.responseText).error || msg; } catch (e) { /* ignore */ }
                done(msg);
            });
        }
    }

    /**
     * Discard changes and revert to the last saved content.
     */
    function discardChanges() {
        if (!state.isDirty) return;
        _showConfirmModal('Discard Changes', 'Discard all unsaved changes?', function () {
            state.cmEditor.setValue(state.originalContent);
            state.isDirty = false;
            _updateDirtyState();
        }, { okText: 'Discard', okClass: 'btn-warning' });
    }


    /**
     * Reload the currently open file from disk.
     * Prompts for confirmation if there are unsaved changes.
     * Fetches fresh content via GET /file-browser/read and replaces editor contents.
     */
    function _reloadFromDisk() {
        if (!state.currentPath) return;

        if (state.isDirty) {
            _showConfirmModal('Reload from Disk', 'You have unsaved changes. Reload from disk? All changes will be lost.', function () {
                _doReload();
            }, { okText: 'Reload', okClass: 'btn-warning' });
            return;
        }
        _doReload();
    }

    /**
     * Internal: perform the actual reload from server.
     */
    function _doReload() {

        $.get(_ep('read'), { path: state.currentPath }, function(resp) {
            if (resp.status === 'error') {
                showToast('Reload failed: ' + (resp.message || 'Unknown error'), 'danger');
                return;
            }
            if (resp.is_binary) {
                showToast('File is now binary \u2014 cannot display', 'warning');
                return;
            }
            if (resp.too_large) {
                showToast('File is now too large (> 2 MB)', 'warning');
                return;
            }
            var cursor = state.cmEditor.getCursor();
            var scrollInfo = state.cmEditor.getScrollInfo();
            state.cmEditor.setValue(resp.content);
            state.originalContent = resp.content;
            state.isDirty = false;
            _updateDirtyState();
            // Restore cursor and scroll position
            state.cmEditor.setCursor(cursor);
            state.cmEditor.scrollTo(scrollInfo.left, scrollInfo.top);
            showToast('Reloaded from disk', 'success');
        }).fail(function(xhr) {
            if (xhr.status === 404) {
                showToast('File no longer exists on disk', 'danger');
            } else {
                showToast('Reload failed: ' + (xhr.statusText || 'Server error'), 'danger');
            }
        });
    }

    // ═══════════════════════════════════════════════════════════════
    //  Markdown preview
    // ═══════════════════════════════════════════════════════════════

    /**
     * Render the current file content as markdown preview.
     */
    function _renderPreview() {
        if (!state.cmEditor) return;
        var content = state.cmEditor.getValue();
        var html;

        // Try to use the project's renderMarkdownToHtml if available
        if (typeof renderMarkdownToHtml === 'function') {
            html = renderMarkdownToHtml(content);
        } else if (typeof marked !== 'undefined') {
            html = marked.marked ? marked.marked(content) : marked(content);
        } else {
            html = '<pre>' + $('<span>').text(content).html() + '</pre>';
        }

        var $container = _$('previewContainer');
        $container.html(html);

        // Apply syntax highlighting to code blocks
        if (typeof hljs !== 'undefined') {
            $container.find('pre code').each(function () {
                hljs.highlightElement(this);
            });
        }
    }

    // ═══════════════════════════════════════════════════════════════
    //  CRUD operations (context menu)
    // ═══════════════════════════════════════════════════════════════

    /**
     * Show the context menu at the given mouse position.
     * @param {number} x - Horizontal position.
     * @param {number} y - Vertical position.
     */
    function _showContextMenu(x, y) {
        if (_config.buildContextMenu && state.contextTarget) {
            var items = _config.buildContextMenu(state.contextTarget.path, state.contextTarget.type);
            if (items !== null && items !== undefined) {
                var $menu = _$('contextMenu');
                var $ul = $menu.find('ul').length ? $menu.find('ul') : $menu;
                $ul.empty();
                items.forEach(function(item) {
                    var $a = $('<a href="#" class="dropdown-item"></a>')
                        .html('<i class="' + (item.icon || '') + ' mr-2"></i>' + item.label)
                        .on('click', function(e) {
                            e.preventDefault();
                            _hideContextMenu();
                            item.action(state.contextTarget.path, state.contextTarget.type);
                        });
                    $ul.append($('<li></li>').append($a));
                });
                $menu.css({ left: x, top: y, display: 'block' });
                return;
            }
        }
        // Default behavior: show standard context menu with flag guards
        var $menu = _$('contextMenu');
        // Apply flag guards to default menu items
        $menu.find('[data-action="new-file"]').toggle(_config.allowCreate && !_config.readOnly);
        $menu.find('[data-action="new-folder"]').toggle(_config.allowCreate && !_config.readOnly);
        $menu.find('[data-action="rename"]').toggle(_config.allowRename && !_config.readOnly);
        $menu.find('[data-action="delete"]').toggle(_config.allowDelete && !_config.readOnly);
        $menu.find('[data-action="move"]').toggle(_config.allowMove && !_config.readOnly);
        $menu.css({ left: x, top: y, display: 'block' });
    }

    /**
     * Hide the context menu.
     */
    function _hideContextMenu() {
        _$('contextMenu').hide();
        state.contextTarget = null;
    }

    // ═══════════════════════════════════════════════════════════════
    //  Move file/folder (drag-and-drop + context menu)
    // ═══════════════════════════════════════════════════════════════

    /**
     * Validate whether srcPath can be moved into destDirPath.
     * @param {string} srcPath     - Full relative path of item being moved.
     * @param {string} destDirPath - Full relative path of target directory.
     * @returns {boolean} true if the move is valid.
     */
    function _isValidMoveTarget(srcPath, destDirPath) {
        // Cannot drop onto itself
        if (srcPath === destDirPath) return false;
        // Cannot drop into own descendant (would make directory vanish)
        if (destDirPath.indexOf(srcPath + '/') === 0) return false;
        // No-op: source is already in this directory
        if (_parentDir(srcPath) === destDirPath) return false;
        return true;
    }

    /**
     * Execute the move: call the configured onMove callback, update state, refresh tree.
     * @param {string} srcPath  - Relative path of item to move.
     * @param {string} destPath - Full new relative path (destDir + '/' + basename).
     */
    function _moveItem(srcPath, destPath) {
        $('#fb-move-ok-btn').prop('disabled', true).text('Moving…');
        _config.onMove(srcPath, destPath, function (err) {
            if (err) {
                showToast(err, 'error');
                $('#fb-move-ok-btn').prop('disabled', false).text('Move Here');
                return;
            }
            // If the currently open file was moved, update its path
            if (state.currentPath === srcPath) {
                state.currentPath = destPath;
                _$('addressBar').val(destPath);
            }
            _hideMoveModal();
            _refreshTree();
            showToast('Moved to ' + _parentDir(destPath), 'success');
        });
    }

    /**
     * Show the move destination modal for state.moveTarget.
     * Populates the folder tree starting from root.
     */
    function _showMoveModal() {
        if (!state.moveTarget) return;
        state.moveDest = null;
        $('#fb-move-src-name').text(state.moveTarget.name);
        $('#fb-move-dest-hint').text('');
        $('#fb-move-ok-btn').prop('disabled', true).text('Move Here');
        var $tree = $('#fb-move-folder-tree').empty();

        // Always show a selectable root item at the top
        var $root = $('<div></div>')
            .addClass('fb-move-dir-item fb-move-root-item')
            .attr('data-path', '.')
            .attr('data-type', 'dir')
            .html('<i class="bi bi-house-door mr-1" style="color:#e6a817;"></i><strong>/ (root)</strong>');
        $tree.append($root);

        // Then load the sub-folder tree below it
        _loadMoveTree('.', $tree);
        _$('moveModal').css('display', 'flex');
    }

    /**
     * Load folder-only tree inside the move modal.
     * Only directories are rendered (files are hidden).
     * @param {string} dirPath   - Directory path to load.
     * @param {jQuery} $container - Container element to append the <ul> into.
     */
    function _loadMoveTree(dirPath, $container) {
        $.getJSON(_ep('tree'), { path: dirPath })
            .done(function (resp) {
                if (resp.status !== 'success') return;
                var entries = (resp.entries || []).filter(function (e) { return e.type === 'dir'; });
                if (!entries.length) {
                    $container.append('<p class="text-muted small p-2 mb-0">(no sub-folders)</p>');
                    return;
                }
                var $ul = $('<ul></ul>').css({ 'list-style': 'none', 'padding-left': '0', 'margin': '0' });
                entries.forEach(function (entry) {
                    var entryPath = _joinPath(dirPath, entry.name);
                    var $li = $('<li></li>')
                        .attr('data-path', entryPath)
                        .attr('data-type', 'dir')
                        .addClass('fb-move-dir-item');
                    var $toggle = $('<span class="fb-move-toggle" style="display:inline-block;width:14px;text-align:center;font-size:0.7rem;color:#888;cursor:pointer;">▶</span>');
                    var $icon = $('<i class="bi bi-folder2 mr-1" style="color:#e6a817;"></i>');
                    var $name = $('<span></span>').text(entry.name);
                    $li.append($toggle).append($icon).append($name);
                    var $children = $('<div class="fb-move-children" style="padding-left:14px; display:none;"></div>');
                    $li.append($children);
                    $ul.append($li);
                });
                $container.append($ul);
            });
    }

    /** Hide the move modal and reset move state. */
    function _hideMoveModal() {
        _$('moveModal').hide();
        state.moveTarget = null;
        state.moveDest = null;
    }

    /** Called when user clicks 'Move Here' in the move modal. */
    function _confirmMove() {
        if (!state.moveTarget || !state.moveDest) return;
        var srcPath = state.moveTarget.path;
        var destPath = _joinPath(state.moveDest, _basename(srcPath));
        if (!_isValidMoveTarget(srcPath, state.moveDest)) {
            showToast('Cannot move a folder into itself or the same location.', 'warning');
            return;
        }
        _moveItem(srcPath, destPath);
    }


    // ═══════════════════════════════════════════════════════════════
    //  Naming modal helpers
    // ═══════════════════════════════════════════════════════════════

    /**
     * Determine the target directory for new file/folder creation.
     * Priority: contextTarget (if set) → parent of currentPath → currentDir.
     * If contextTarget or currentPath is a file, its parent directory is used.
     * @returns {string} Relative directory path.
     */
    function _getTargetDir() {
        if (state.contextTarget) {
            if (state.contextTarget.type === 'file') {
                return _parentDir(state.contextTarget.path);
            }
            return state.contextTarget.path;
        }
        if (state.currentPath) {
            return _parentDir(state.currentPath);
        }
        return state.currentDir;
    }

    /**
     * Show the naming modal overlay for creating a new file/folder or renaming.
     * @param {'file'|'folder'|'rename'} type - The operation type.
     * @param {function} callback - Called with the entered name string when user confirms.
     * @param {object} [opts] - Optional settings.
     * @param {string} [opts.currentName] - Pre-fill value (used for rename).
     * @param {string} [opts.dir] - Directory hint override.
     */
    function _showNameModal(type, callback, opts) {
        opts = opts || {};
        var dir = opts.dir || _getTargetDir();
        var $modal = _$('nameModal');
        var $input = _$('nameInput');
        var $title = _$('nameTitle');
        var $hint = _$('nameHint');
        var $dirHint = _$('nameDirHint');
        var $okBtn = _$('nameOkBtn');

        if (type === 'rename') {
            $title.text('Rename');
            $hint.html('In: <span id="file-browser-name-modal-dir">' + (dir === '.' ? '/ (root)' : _escHtml(dir)) + '</span>');
            $input.val(opts.currentName || '');
            $okBtn.text('Rename');
        } else {
            $title.text(type === 'file' ? 'New File' : 'New Folder');
            $hint.html('Will be created in: <span id="file-browser-name-modal-dir">' + (dir === '.' ? '/ (root)' : _escHtml(dir)) + '</span>');
            $input.val('');
            $okBtn.text('Create');
        }
        $modal.css('display', 'flex');
        setTimeout(function () {
            $input.focus();
            if (type === 'rename') $input.select();
        }, 50);
        // Store callback for OK button / Enter key
        $modal.data('_nameCallback', callback);
        $modal.data('_nameDir', dir);
    }

    /**
     * Hide the naming modal overlay and clear callback state.
     */
    function _hideNameModal() {
        var $modal = _$('nameModal');
        $modal.css('display', 'none');
        $modal.removeData('_nameCallback');
        $modal.removeData('_nameDir');
    }

    /**
     * Handle OK action from naming modal \u2014 reads input, validates, fires callback.
     */
    function _nameModalConfirm() {
        var $modal = _$('nameModal');
        var $input = _$('nameInput');
        var name = $input.val().trim();
        if (!name) {
            $input.addClass('is-invalid');
            setTimeout(function () { $input.removeClass('is-invalid'); }, 1500);
            return;
        }
        var callback = $modal.data('_nameCallback');
        _hideNameModal();
        if (typeof callback === 'function') {
            callback(name);
        }
    }

    // \u2500\u2500\u2500 Confirm dialog (async, callback-based) \u2500\u2500\u2500

    /**
     * Show a confirmation dialog inside the file browser.
     * Replaces native confirm() which gets blocked behind high z-index modals.
     * @param {string} title - Dialog title.
     * @param {string} bodyHtml - Message body (can contain HTML).
     * @param {function} onConfirm - Called (no args) when user clicks OK.
     * @param {object} [opts] - Optional settings.
     * @param {string} [opts.okText] - Custom OK button text (default: 'OK').
     * @param {string} [opts.okClass] - Custom OK button class (default: 'btn-danger').
     */
    function _showConfirmModal(title, bodyHtml, onConfirm, opts) {
        opts = opts || {};
        var $modal = _$('confirmModal');
        _$('confirmTitle').text(title);
        _$('confirmBody').html(bodyHtml);
        var $okBtn = _$('confirmOkBtn');
        $okBtn.text(opts.okText || 'OK');
        $okBtn.attr('class', 'btn btn-sm ' + (opts.okClass || 'btn-danger'));
        $modal.data('_confirmCallback', onConfirm);
        $modal.css('display', 'flex');
        $okBtn.focus();
    }

    /**
     * Hide the confirmation dialog and clear callback.
     */
    function _hideConfirmModal() {
        var $modal = _$('confirmModal');
        $modal.css('display', 'none');
        $modal.removeData('_confirmCallback');
    }

    /**
     * Create a new file — shows naming modal, then calls the write API.
     * Uses _getTargetDir() to determine which folder to create in.
     */
    function _createFile() {
        _showNameModal('file', function (name) {
            var dir = _getTargetDir();
            var filePath = _joinPath(dir, name);
            var done = function(err) {
                if (err) { showToast('Create failed: ' + err, 'error'); return; }
                showToast('Created: ' + name, 'success');
                _refreshTree();
                loadFile(filePath);
            };
            if (_config.onCreateFile) {
                _config.onCreateFile(filePath, done);
            } else {
                if (!_ep('write')) { done('Not supported'); return; }
                $.ajax({
                    url: _ep('write'),
                    method: 'POST',
                    contentType: 'application/json',
                    data: JSON.stringify({ path: filePath, content: '' })
                })
                .done(function (resp) {
                    if (resp.status === 'success') {
                        done(null);
                    } else {
                        done(resp.error || 'Unknown');
                    }
                })
                .fail(function (xhr) {
                    var msg = 'Create failed';
                    try { msg = JSON.parse(xhr.responseText).error || msg; } catch (e) { /* ignore */ }
                    done(msg);
                });
            }
        });
    }

    /**
     * Create a new folder — shows naming modal, then calls the mkdir API.
     * Uses _getTargetDir() to determine which folder to create in.
     */
    function _createFolder() {
        _showNameModal('folder', function (name) {
            var dir = _getTargetDir();
            var folderPath = _joinPath(dir, name);
            var done = function(err) {
                if (err) { showToast('Create folder failed: ' + err, 'error'); return; }
                showToast('Created folder: ' + name, 'success');
                _refreshTree();
            };
            if (_config.onCreateFolder) {
                _config.onCreateFolder(folderPath, done);
            } else {
                if (!_ep('mkdir')) { done('Not supported'); return; }
                $.ajax({
                    url: _ep('mkdir'),
                    method: 'POST',
                    contentType: 'application/json',
                    data: JSON.stringify({ path: folderPath })
                })
                .done(function (resp) {
                    if (resp.status === 'success') {
                        done(null);
                    } else {
                        done(resp.error || 'Unknown');
                    }
                })
                .fail(function (xhr) {
                    var msg = 'Create folder failed';
                    try { msg = JSON.parse(xhr.responseText).error || msg; } catch (e) { /* ignore */ }
                    done(msg);
                });
            }
        });
    }

    /**
     * Rename a file or folder via prompt and API call.
     */
    function _renameItem() {
        if (!state.contextTarget) return;
        var oldPath = state.contextTarget.path;
        var oldName = _basename(oldPath);
        var dir = _parentDir(oldPath);
        _showNameModal('rename', function (newName) {
            if (!newName || newName === oldName) return;
            var newPath = _joinPath(dir, newName);
            var done = function(err) {
                if (err) { showToast('Rename failed: ' + err, 'error'); return; }
                showToast('Renamed to: ' + newName, 'success');
                if (state.currentPath === oldPath) {
                    state.currentPath = newPath;
                    _$('addressBar').val(newPath);
                }
                _refreshTree();
            };
            if (_config.onRename) {
                _config.onRename(oldPath, newPath, done);
            } else {
                if (!_ep('rename')) { done('Not supported'); return; }
                $.ajax({
                    url: _ep('rename'),
                    method: 'POST',
                    contentType: 'application/json',
                    data: JSON.stringify({ old_path: oldPath, new_path: newPath })
                })
                .done(function (resp) {
                    if (resp.status === 'success') {
                        done(null);
                    } else {
                        done(resp.error || 'Unknown');
                    }
                })
                .fail(function (xhr) {
                    var msg = 'Rename failed';
                    try { msg = JSON.parse(xhr.responseText).error || msg; } catch (e) { /* ignore */ }
                    done(msg);
                });
            }
        }, { currentName: oldName, dir: dir });
    }

    /**
     * Delete a file or folder via confirmation dialog and API call.
     */
    function _deleteItem() {
        if (!state.contextTarget) return;
        var itemPath = state.contextTarget.path;
        var itemType = state.contextTarget.type;
        var itemName = _basename(itemPath);
        var bodyHtml = 'Delete <strong>' + _escHtml(itemName) + '</strong>?';
        if (itemType === 'dir') {
            bodyHtml += '<br><small class="text-muted">This will delete the folder and ALL its contents.</small>';
        }

        _showConfirmModal('Delete', bodyHtml, function () {
            var done = function(err) {
                if (err) { showToast('Delete failed: ' + err, 'error'); return; }
                showToast('Deleted: ' + itemName, 'success');
                if (state.currentPath === itemPath) {
                    state.currentPath = null;
                    _$('aiEditBtn').prop('disabled', true);
                    _$('reloadBtn').prop('disabled', true);
                    _$('wrapBtn').prop('disabled', true);
                    _$('downloadBtn').prop('disabled', true);
                    state.originalContent = '';
                    state.isDirty = false;
                    _updateDirtyState();
                    _$('addressBar').val('');
                    _$('tabBar').hide();
                    _showView('empty');
                }
                _refreshTree();
            };
            if (_config.onDelete) {
                _config.onDelete(itemPath, done);
            } else {
                if (!_ep('delete')) { done('Not supported'); return; }
                $.ajax({
                    url: _ep('delete'),
                    method: 'POST',
                    contentType: 'application/json',
                    data: JSON.stringify({ path: itemPath, recursive: (itemType === 'dir') })
                })
                .done(function (resp) {
                    if (resp.status === 'success') {
                        done(null);
                    } else {
                        done(resp.error || 'Unknown');
                    }
                })
                .fail(function (xhr) {
                    var msg = 'Delete failed';
                    try { msg = JSON.parse(xhr.responseText).error || msg; } catch (e) { /* ignore */ }
                    done(msg);
                });
            }
        }, { okText: 'Delete' });
    }

    /**
     * Refresh the entire file tree, preserving expanded directories.
     */
    function _refreshTree() {
        loadTree('.', null);
    }

    // ═══════════════════════════════════════════════════════════════
    //  Sidebar toggle
    // ═══════════════════════════════════════════════════════════════

    /**
     * Toggle the sidebar visibility with a CSS transition.
     */
    function _toggleSidebar() {
        state.sidebarVisible = !state.sidebarVisible;
        var $sidebar = _$('sidebar');
        if (state.sidebarVisible) {
            $sidebar.removeClass('collapsed');
            _$('sidebarToggle').find('i').attr('class', 'bi bi-layout-sidebar');
            // Show the view-mode tab bar together with the sidebar (markdown only)
            if (state.isMarkdown) {
                _$('tabBar').show();
            }
        } else {
            $sidebar.addClass('collapsed');
            _$('sidebarToggle').find('i').attr('class', 'bi bi-layout-sidebar-inset');
            // Hide the view-mode tab bar when sidebar collapses
            _$('tabBar').hide();
        }
        // Refresh CodeMirror after CSS transition completes
        setTimeout(function () {
            if (state.cmEditor) state.cmEditor.refresh();
        }, 250);
    }

    // ═══════════════════════════════════════════════════════════════
    //  Address bar navigation
    // ═══════════════════════════════════════════════════════════════

    /**
     * Navigate to a path typed in the address bar.
     * Tries to load as a file first, then falls back to directory navigation.
     * @param {string} inputPath - Path typed by the user.
     */
    function _navigateAddressBar(inputPath) {
        if (!inputPath || inputPath.trim() === '') {
            // Empty path → go to root
            state.currentDir = '.';
            _refreshTree();
            return;
        }
        var path = inputPath.trim();

        // Try as a file first
        $.getJSON(_ep('read'), { path: path })
            .done(function (resp) {
                if (resp.status === 'success') {
                    loadFile(path);
                    return;
                }
                // Not a file, try as directory
                _tryAsDirectory(path);
            })
            .fail(function () {
                _tryAsDirectory(path);
            });
    }

    /**
     * Try navigating to a directory path.
     * @param {string} path - Relative directory path.
     */
    function _tryAsDirectory(path) {
        $.getJSON(_ep('tree'), { path: path })
            .done(function (resp) {
                if (resp.status === 'success') {
                    state.currentDir = path;
                    // Expand all parent directories
                    var parts = path.split('/');
                    var cumulative = '';
                    for (var i = 0; i < parts.length; i++) {
                        cumulative = cumulative ? cumulative + '/' + parts[i] : parts[i];
                        state.expandedDirs[cumulative] = true;
                    }
                    _refreshTree();
                } else {
                    showToast('Path not found', 'error');
                }
            })
            .fail(function () {
                showToast('Path not found', 'error');
            });
    }

    // ═══════════════════════════════════════════════════════════════
    //  Modal open / close
    // ═══════════════════════════════════════════════════════════════

    /**
     * Open the file browser modal. Stacks on top of whatever is showing
     * (including the settings modal) — bypasses Bootstrap modal JS entirely
     * to avoid stacking/backdrop issues.
     */
    function open(path) {
        console.log('[FileBrowser] open() called');
        if (path) { state.currentDir = path; }
        _showFileBrowserModal();
    }

    /**
     * Apply behavior-flag guards: show/hide toolbar buttons and panels
     * based on _config flags (readOnly, allowCreate, allowUpload, etc.).
     * Called each time the modal opens so runtime configure() changes take effect.
     */
    function _applyBehaviorFlags() {
        var ro = _config.readOnly;
        _$('saveBtn').toggle(!ro && !!_ep('write'));
        _$('discardBtn').toggle(!ro && !!_ep('write'));
        _$('newFileBtn').toggle(!ro && _config.allowCreate && !!_ep('write'));
        _$('newFolderBtn').toggle(!ro && _config.allowCreate && !!_ep('mkdir'));
        _$('uploadBtn').toggle(!ro && _config.allowUpload && !!_ep('upload'));
        _$('reloadBtn').toggle(!!_ep('read'));
        _$('downloadBtn').toggle(!!_ep('download'));
        _$('aiEditBtn').toggle(!ro && _config.allowAiEdit && !!_ep('aiEdit'));
        if (!_config.showEditor) {
            _$('editorContainer').hide();
            _$('previewContainer').hide();
            _$('wysiwygContainer').hide();
            _$('tabBar').hide();
        }
        if (!_config.showAddressBar) {
            _$('addressBar').closest('.fb-address-bar-wrap').hide();
        }
    }

    /**
     * Show the file browser by manually toggling CSS classes and creating
     * our own backdrop. Bootstrap's .modal('show') fights with already-open
     * modals, so we bypass it completely.
     */
    function _showFileBrowserModal() {
        var modal = document.getElementById(_config.dom.modal);
        if (!modal || modal.classList.contains('show')) return;
        console.log('[FileBrowser] Showing modal manually');
        // Kill any stale backdrop left by old cached JS
        var staleBackdrop = document.getElementById(_config.dom.backdrop);
        if (staleBackdrop) staleBackdrop.remove();
        // Dismiss any stale confirm/name dialogs left over from a prior session
        _hideConfirmModal();
        _hideNameModal();

        modal.style.display = 'block';
        modal.classList.add('show');
        modal.setAttribute('aria-hidden', 'false');
        document.body.classList.add('modal-open');
        var startDir = _config.rootPath || '.';
        state.currentDir = startDir;
        setTimeout(function () {
            _ensureEditor();
            if (state.cmEditor) state.cmEditor.refresh();
            if (Object.keys(state.expandedDirs).length === 0 && !state.currentPath) {
                loadTree(startDir, null);
            }
        }, 50);
        _applyBehaviorFlags();
        if (_config.onOpen) _config.onOpen();
    }

    /**
     * Close the file browser modal. Prompts if unsaved changes.
     * Removes our custom backdrop. Leaves the settings modal intact underneath.
     */
    function _closeModal() {
        // Guard: if confirm modal is already visible (e.g. from a previous close attempt),
        // don't re-trigger — just let the user respond to the existing dialog.
        if (_$('confirmModal').css('display') === 'flex') return;
        _confirmIfDirty(function () {
            if (_config.onClose) _config.onClose();
            var modal = document.getElementById(_config.dom.modal);
            if (modal) {
                modal.classList.remove('show');
                modal.style.display = 'none';
                modal.setAttribute('aria-hidden', 'true');
            }
            // Clean up PDF blob URL to free memory
            if (state.pdfBlobUrl) {
                URL.revokeObjectURL(state.pdfBlobUrl);
                state.pdfBlobUrl = null;
            }
            // Sync WYSIWYG before close
            if (state.viewMode === 'wysiwyg') {
                _syncWysiwygToCodeMirror();
            }
            // Remove stale backdrop from old cached JS
            var staleBackdrop = document.getElementById(_config.dom.backdrop);
            if (staleBackdrop) staleBackdrop.remove();
            // Remove any orphan Bootstrap backdrops
            $('.modal-backdrop').each(function () {
                if (!$(this).closest('.modal').length) $(this).remove();
            });
            if ($('.modal.show').length === 0) {
                document.body.classList.remove('modal-open');
            }
        });
    }


    // ═══════════════════════════════════════════════════════════════
    //  AI Edit functions
    // ═══════════════════════════════════════════════════════════════

    function _showAiEditModal() {
        if (!state.cmEditor || !state.currentPath) {
            showToast('No file open', 'warning');
            return;
        }

        // Capture selection info
        if (state.cmEditor.somethingSelected()) {
            var from = state.cmEditor.getCursor('from');
            var to = state.cmEditor.getCursor('to');
            // Expand to full lines
            state.aiEditSelection = {
                from: {line: from.line, ch: 0},
                to: {line: to.line, ch: state.cmEditor.getLine(to.line).length}
            };
            state.aiEditStartLine = from.line + 1;  // 1-indexed
            state.aiEditEndLine = to.line + 1;
            state.aiEditIsSelection = true;
            $('#fb-ai-edit-info').text('Editing: lines ' + state.aiEditStartLine + '-' + state.aiEditEndLine + ' (selected)');
        } else {
            state.aiEditSelection = null;
            state.aiEditStartLine = null;
            state.aiEditEndLine = null;
            state.aiEditIsSelection = false;
            var totalLines = state.cmEditor.lineCount();
            if (totalLines > 500) {
                showToast('File too large for whole-file AI edit (' + totalLines + ' lines). Please select a region.', 'warning');
                return;
            }
            $('#fb-ai-edit-info').text('Editing: entire file');
        }

        // Check if conversation is available
        var convId = (typeof getConversationIdFromUrl === 'function') ? getConversationIdFromUrl() : null;
        if (convId) {
            $('#fb-ai-edit-include-summary, #fb-ai-edit-include-messages, #fb-ai-edit-include-memory, #fb-ai-edit-deep-context').prop('disabled', false).closest('.form-check').css('opacity', '1');
            $('#fb-ai-edit-history-count').prop('disabled', false);
        } else {
            $('#fb-ai-edit-include-summary, #fb-ai-edit-include-messages, #fb-ai-edit-include-memory, #fb-ai-edit-deep-context').prop('disabled', true).prop('checked', false).closest('.form-check').css('opacity', '0.5');
            $('#fb-ai-edit-history-count').prop('disabled', true);
        }

        // Show the modal
        var modal = document.getElementById(_config.dom.aiEditModal);
        modal.style.display = 'flex';
        setTimeout(function() {
            $('#fb-ai-edit-instruction').focus();
        }, 50);
    }

    function _hideAiEditModal() {
        var modal = document.getElementById(_config.dom.aiEditModal);
        modal.style.display = 'none';
        $('#fb-ai-edit-spinner').hide();
        $('#fb-ai-edit-generate').prop('disabled', false);
    }

    function _generateAiEdit() {
        var instruction = ($('#fb-ai-edit-instruction').val() || '').trim();
        if (!instruction) {
            showToast('Please enter an instruction', 'warning');
            return;
        }

        // Show spinner
        $('#fb-ai-edit-spinner').show();
        $('#fb-ai-edit-generate').prop('disabled', true);

        var convId = (typeof getConversationIdFromUrl === 'function') ? getConversationIdFromUrl() : null;
        var payload = {
            path: state.currentPath,
            instruction: instruction,
            include_summary: $('#fb-ai-edit-include-summary').is(':checked'),
            include_messages: $('#fb-ai-edit-include-messages').is(':checked'),
            include_memory_pad: $('#fb-ai-edit-include-memory').is(':checked'),
            history_count: parseInt($('#fb-ai-edit-history-count').val() || '10', 10),
            deep_context: $('#fb-ai-edit-deep-context').is(':checked')
        };
        var anyContextRequested = payload.include_summary || payload.include_messages || payload.include_memory_pad || payload.deep_context;
        if (convId && anyContextRequested) {
            payload.conversation_id = convId;
        }
        if (state.aiEditIsSelection && state.aiEditStartLine && state.aiEditEndLine) {
            payload.selection = {
                start_line: state.aiEditStartLine,
                end_line: state.aiEditEndLine
            };
        }

        $.ajax({
            url: _ep('aiEdit'),
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify(payload)
        })
        .done(function(resp) {
            if (resp.status === 'error') {
                showToast(resp.error || 'AI edit failed', 'error');
                _hideAiEditModal();
                return;
            }
            state.aiEditProposed = resp.proposed;
            state.aiEditOriginal = resp.original;
            state.aiEditBaseHash = resp.base_hash;
            if (resp.is_selection) {
                state.aiEditStartLine = resp.start_line;
                state.aiEditEndLine = resp.end_line;
            }
            _hideAiEditModal();
            _showAiDiffModal(resp.diff_text);
        })
        .fail(function(xhr) {
            var msg = 'AI edit request failed';
            try { msg = JSON.parse(xhr.responseText).error || msg; } catch (e) { /* ignore */ }
            showToast(msg, 'error');
            _hideAiEditModal();
        });
    }

    function _showAiDiffModal(diffText) {
        state.aiEditLastDiffText = diffText || null;
        var container = document.getElementById('fb-ai-diff-content');
        container.innerHTML = _renderDiffPreview(diffText);
        var modal = document.getElementById(_config.dom.aiDiffModal);
        modal.style.display = 'flex';
    }

    function _hideAiDiffModal() {
        var modal = document.getElementById(_config.dom.aiDiffModal);
        modal.style.display = 'none';
        document.getElementById('fb-ai-diff-content').innerHTML = '';
    }

    function _acceptAiEdit() {
        if (!state.aiEditProposed) {
            showToast('No proposed edit to accept', 'warning');
            _hideAiDiffModal();
            return;
        }

        if (state.aiEditIsSelection && state.aiEditSelection) {
            // Replace the selected range
            state.cmEditor.replaceRange(
                state.aiEditProposed,
                state.aiEditSelection.from,
                state.aiEditSelection.to
            );
        } else {
            // Replace entire file content
            var cursor = state.cmEditor.getCursor();
            state.cmEditor.setValue(state.aiEditProposed);
            state.cmEditor.setCursor(cursor);
        }

        state.isDirty = true;
        _updateDirtyState();
        _hideAiDiffModal();
        _clearAiEditState();
        showToast('AI edit applied. Review and save when ready.', 'success');
    }

    function _rejectAiEdit() {
        _hideAiDiffModal();
        _clearAiEditState();
    }

    function _editAiInstruction() {
        _hideAiDiffModal();
        // Append the previous diff as context so the user can give follow-up instructions.
        var $ta = $('#fb-ai-edit-instruction');
        var prev = ($ta.val() || '').replace(/\s+$/, '');
        if (prev && state.aiEditLastDiffText) {
            // Build a compact summary: count added/removed lines
            var added = 0, removed = 0;
            (state.aiEditLastDiffText || '').split('\n').forEach(function(l) {
                if (l.charAt(0) === '+' && l.indexOf('+++') !== 0) added++;
                if (l.charAt(0) === '-' && l.indexOf('---') !== 0) removed++;
            });
            var summary = '\n\n--- Previous result: +' + added + ' / -' + removed +
                ' lines. Give additional instructions below: ---\n';
            $ta.val(prev + summary);
        }
        var modal = document.getElementById(_config.dom.aiEditModal);
        modal.style.display = 'flex';
        setTimeout(function() {
            var el = $ta[0];
            el.focus();
            el.setSelectionRange(el.value.length, el.value.length);
        }, 50);
    }

    function _clearAiEditState() {
        state.aiEditProposed = null;
        state.aiEditOriginal = null;
        state.aiEditBaseHash = null;
        state.aiEditLastDiffText = null;
    }

    function _renderDiffPreview(diffText) {
        if (!diffText) return '<div class="text-muted p-2">No changes detected</div>';
        var lines = diffText.split('\n');
        var html = '';
        for (var i = 0; i < lines.length; i++) {
            var line = lines[i];
            var escaped = line.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
            var cls = 'ai-diff-line';
            if (line.indexOf('@@') === 0) {
                cls += ' ai-diff-hunk';
            } else if (line.indexOf('+++') === 0 || line.indexOf('---') === 0) {
                cls += ' ai-diff-header';
            } else if (line.indexOf('+') === 0) {
                cls += ' ai-diff-add';
            } else if (line.indexOf('-') === 0) {
                cls += ' ai-diff-del';
            }
            html += '<div class="' + cls + '">' + escaped + '</div>';
        }
        return html;
    }

    // ═══════════════════════════════════════════════════════════════
    //  Download / Upload helpers
    // ═══════════════════════════════════════════════════════════════

    /**
     * Trigger a browser file download for the currently open file.
     * Uses a temporary <a> with the /file-browser/download URL.
     */
    function _downloadFile() {
        if (!state.currentPath) return;
        var url = _ep('download') + '?path=' + encodeURIComponent(state.currentPath);
        var a = document.createElement('a');
        a.href = url;
        a.download = state.currentPath.split('/').pop();
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
    }

    /**
     * Return the target upload directory: directory of current file,
     * directory currently browsed, or '.' (root) as fallback.
     */
    function _getUploadDir() {
        if (state.currentPath) {
            var parts = state.currentPath.replace(/\\/g, '/').split('/');
            parts.pop();
            return parts.length ? parts.join('/') : '.';
        }
        if (state.currentDir && state.currentDir !== '.') return state.currentDir;
        return '.';
    }

    /** Pending file object for the upload modal. */
    var _uploadPendingFile = null;

    function _showUploadModal() {
        _uploadPendingFile = null;
        var dir = _getUploadDir();
        $('#fb-upload-dir-hint').text('Uploading to: ' + (dir === '.' ? '/ (root)' : dir));
        $('#fb-upload-filename').text('');
        $('#fb-upload-progress-wrap').hide();
        $('#fb-upload-progress-bar').css('width', '0%');
        $('#fb-upload-progress-text').text('0%');
        $('#fb-upload-submit-btn').prop('disabled', true);
        $('#fb-upload-spinner').hide();
        $('#fb-upload-input').val('');
        _$('uploadModal').css('display', 'flex');
    }

    function _hideUploadModal() {
        _$('uploadModal').css('display', 'none');
        _uploadPendingFile = null;
    }

    function _setUploadFile(file) {
        if (!file) return;
        _uploadPendingFile = file;
        $('#fb-upload-filename').text(file.name);
        $('#fb-upload-submit-btn').prop('disabled', false);
    }

    function _doUpload() {
        if (_config.readOnly) return;
        if (!_uploadPendingFile) return;
        var dir = _getUploadDir();

        var done = function(err) {
            $('#fb-upload-spinner').hide();
            $('#fb-upload-cancel-btn').prop('disabled', false);
            if (err) {
                showToast('Upload failed: ' + err, 'error');
                $('#fb-upload-submit-btn').prop('disabled', false);
                return;
            }
            _hideUploadModal();
            _refreshTree();
            showToast('Uploaded: ' + (_uploadPendingFile ? _uploadPendingFile.name : ''), 'success');
        };

        $('#fb-upload-spinner').show();
        $('#fb-upload-submit-btn').prop('disabled', true);
        $('#fb-upload-cancel-btn').prop('disabled', true);
        $('#fb-upload-progress-wrap').show();

        if (_config.onUpload) {
            _config.onUpload(_uploadPendingFile, dir, done);
        } else {
            if (!_ep('upload')) { done('Not supported'); return; }
            var formData = new FormData();
            formData.append('file', _uploadPendingFile);
            formData.append('path', dir);

            var xhr = new XMLHttpRequest();
            xhr.open('POST', _ep('upload'), true);
            xhr.upload.onprogress = function(e) {
                if (e.lengthComputable) {
                    var pct = Math.round((e.loaded / e.total) * 100);
                    $('#fb-upload-progress-bar').css('width', pct + '%');
                    $('#fb-upload-progress-text').text(pct + '%');
                }
            };
            xhr.onload = function() {
                if (xhr.status === 200) {
                    done(null);
                } else {
                    var msg = 'Upload failed';
                    try { msg = JSON.parse(xhr.responseText).error || msg; } catch(e2) { /* ignore */ }
                    done(msg);
                }
            };
            xhr.onerror = function() {
                done('Network error');
            };
            xhr.send(formData);
        }
    }

    // ═══════════════════════════════════════════════════════════════
    //  Initialization
    // ═══════════════════════════════════════════════════════════════

    /**
     * Initialize all event handlers. Called once on page load.
     */
    function init(cfg) {
        if (state.initialized) return;
        state.initialized = true;
        // Merge caller-supplied config (e.g. custom onMove) with defaults
        if (cfg) { $.extend(true, _config, cfg); }
        console.log('[FileBrowser] init() called');
        console.log('[FileBrowser] Button element found:', _$('openBtn').length);
        console.log('[FileBrowser] Modal element found:', _$('modal').length);
        // --- Button to open file browser ---
        _$('openBtn').on('click', function () {
            console.log('[FileBrowser] Button clicked!');
            open();
        });

        // NOTE: shown.bs.modal won't fire because we bypass Bootstrap's modal JS.
        // Editor init and tree loading are handled in _showFileBrowserModal() instead.

        // --- Save button ---
        _$('saveBtn').on('click', function () {
            saveFile();
        });

        // --- Discard button ---
        _$('discardBtn').on('click', function () {
            discardChanges();
        });

        // --- Reload from disk button ---
        _$('reloadBtn').on('click', _reloadFromDisk);

        // --- Word wrap toggle ---
        _$('wrapBtn').on('click', _toggleWordWrap);

        // --- Download button ---
        _$('downloadBtn').on('click', _downloadFile);

        // --- Upload button & modal ---
        _$('uploadBtn').on('click', _showUploadModal);
        $('#fb-upload-close, #fb-upload-cancel-btn').on('click', _hideUploadModal);
        $('#fb-upload-submit-btn').on('click', _doUpload);

        // Browse link / file input
        $('#fb-upload-browse-link').on('click', function(e) {
            e.preventDefault();
            $('#fb-upload-input').click();
        });
        $('#fb-upload-dropzone').on('click', function() {
            $('#fb-upload-input').click();
        });
        $('#fb-upload-input').on('change', function() {
            if (this.files && this.files[0]) _setUploadFile(this.files[0]);
        });

        // Drag-and-drop onto the dropzone
        $('#fb-upload-dropzone').on('dragover', function(e) {
            e.preventDefault();
            $(this).css('background', '#f0f4ff');
        });
        $('#fb-upload-dropzone').on('dragleave', function() {
            $(this).css('background', '');
        });
        $('#fb-upload-dropzone').on('drop', function(e) {
            e.preventDefault();
            $(this).css('background', '');
            var files = e.originalEvent.dataTransfer.files;
            if (files && files[0]) _setUploadFile(files[0]);
        });

        // Backdrop click closes upload modal
        _$('uploadModal').on('click', function(e) {
            if (e.target === this) _hideUploadModal();
        });

        // --- Move modal: button wiring ---
        $('#fb-move-cancel-btn').on('click', _hideMoveModal);
        $('#fb-move-ok-btn').on('click', _confirmMove);
        // Backdrop click cancels
        _$('moveModal').on('click', function (e) {
            if (e.target === this) _hideMoveModal();
        });
        // Folder click inside move tree (delegated)
        $('#fb-move-folder-tree').on('click', '.fb-move-dir-item', function (e) {
            e.stopPropagation();
            var $li = $(this);
            var dirPath = $li.attr('data-path');
            // Select this item
            $('#fb-move-folder-tree .fb-move-dir-item').removeClass('fb-move-selected');
            $li.addClass('fb-move-selected');
            state.moveDest = dirPath;
            var hint = dirPath === '.' ? '/ (root)' : dirPath;
            $('#fb-move-dest-hint').text('Destination: ' + hint);
            $('#fb-move-ok-btn').prop('disabled', false);
            // Toggle sub-folders
            var $children = $li.children('.fb-move-children');
            var $toggle = $li.children('.fb-move-toggle');
            if ($children.children().length) {
                $children.toggle();
                $toggle.text($children.is(':visible') ? '▼' : '▶');
            } else {
                _loadMoveTree(dirPath, $children);
                $children.show();
                $toggle.text('▼');
            }
        });


        // --- Close button ---
        _$('closeBtn').on('click', function () {
            _closeModal();
        });

        // --- Sidebar toggle ---
        _$('sidebarToggle').on('click', function () {
            _toggleSidebar();
        });

        // --- Refresh button ---
        _$('refreshBtn').on('click', function () {
            _refreshTree();
        });


        // --- New File sidebar button ---
        _$('newFileBtn').on('click', function () {
            state.contextTarget = null; // use currentPath / currentDir fallback
            _createFile();
        });

        // --- New Folder sidebar button ---
        _$('newFolderBtn').on('click', function () {
            state.contextTarget = null; // use currentPath / currentDir fallback
            _createFolder();
        });

        // --- Naming modal: OK / Cancel / Enter ---
        _$('nameOkBtn').on('click', function () {
            _nameModalConfirm();
        });
        _$('nameCancelBtn').on('click', function () {
            _hideNameModal();
        });
        _$('nameInput').on('keydown', function (e) {
            if (e.key === 'Enter') {
                e.preventDefault();
                _nameModalConfirm();
            }
            if (e.key === 'Escape') {
                e.preventDefault();
                e.stopPropagation();
                _hideNameModal();
            }
        });
        // Click on backdrop (outside the inner card) closes naming modal
        _$('nameModal').on('click', function (e) {
            if (e.target === this) _hideNameModal();
        });



        // --- Confirm modal: OK / Cancel / Escape ---
        _$('confirmOkBtn').on('click', function () {
            var cb = _$('confirmModal').data('_confirmCallback');
            _hideConfirmModal();
            if (typeof cb === 'function') cb();
        });
        _$('confirmCancelBtn').on('click', function () {
            _hideConfirmModal();
        });
        _$('confirmModal').on('click', function (e) {
            if (e.target === this) _hideConfirmModal();
        });
        $(document).on('keydown', function (e) {
            if (e.key === 'Escape' && _$('confirmModal').css('display') === 'flex') {
                e.stopPropagation();
                _hideConfirmModal();
            }
        });

        // --- AI Edit handlers ---
        _$('aiEditBtn').on('click', function() {
            _showAiEditModal();
        });
        $('#fb-ai-edit-cancel').on('click', function() {
            _hideAiEditModal();
        });
        $('#fb-ai-edit-generate').on('click', function() {
            _generateAiEdit();
        });
        $('#fb-ai-diff-accept').on('click', function() {
            _acceptAiEdit();
        });
        $('#fb-ai-diff-reject').on('click', function() {
            _rejectAiEdit();
        });
        $('#fb-ai-diff-edit').on('click', function() {
            _editAiInstruction();
        });


        // Keyboard shortcuts for AI edit overlays
        $(document).on('keydown', function(e) {
            // Escape closes AI edit overlays (highest priority)
            if (e.key === 'Escape') {
                var diffModal = document.getElementById(_config.dom.aiDiffModal);
                if (diffModal && diffModal.style.display === 'flex') {
                    e.stopPropagation();
                    _rejectAiEdit();
                    return;
                }
                var editModal = document.getElementById(_config.dom.aiEditModal);
                if (editModal && editModal.style.display === 'flex') {
                    e.stopPropagation();
                    _hideAiEditModal();
                    return;
                }
            }
        });

        // Ctrl+Enter / Cmd+Enter in instruction textarea triggers generate
        $('#fb-ai-edit-instruction').on('keydown', function(e) {
            if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
                e.preventDefault();
                _generateAiEdit();
            }
        });

        // Backdrop click to close AI edit modals
        _$('aiEditModal').on('click', function(e) {
            if (e.target === this) _hideAiEditModal();
        });
        _$('aiDiffModal').on('click', function(e) {
            if (e.target === this) _rejectAiEdit();
        });

        // --- Address bar: input for fuzzy suggestions ---
        _$('addressBar').on('input', function () {
            _filterAndShowSuggestions($(this).val().trim());
        });

        // --- Address bar: keyboard navigation (arrows, Enter, Escape) ---
        _$('addressBar').on('keydown', function (e) {
            // Arrow keys and Enter for suggestion navigation
            if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
                if (_handleSuggestionNav(e.key)) {
                    e.preventDefault();
                    return;
                }
            }
            if (e.key === 'Enter') {
                e.preventDefault();
                // If a suggestion is highlighted, select it
                if (_handleSuggestionNav('Enter')) return;
                // Otherwise navigate to typed path
                _hideSuggestionDropdown();
                _navigateAddressBar($(this).val());
                return;
            }
            if (e.key === 'Escape') {
                var $dd = _$('suggestionDropdown');
                if ($dd.css('display') !== 'none') {
                    e.stopPropagation();
                    _hideSuggestionDropdown();
                    return;
                }
            }
        });

        // --- Address bar: click on suggestion item ---
        $(document).on('click', '.fb-suggestion-item', function () {
            var selectedPath = $(this).attr('data-path');
            if (selectedPath) {
                _$('addressBar').val(selectedPath);
                _hideSuggestionDropdown();
                _navigateAddressBar(selectedPath);
            }
        });

        // --- Address bar: close dropdown on outside click ---
        $(document).on('mousedown', function (e) {
            if (!$(e.target).closest('#' + _config.dom.addressBar + ', #' + _config.dom.suggestionDropdown).length) {
                _hideSuggestionDropdown();
            }
        });

        // --- Address bar: focus shows suggestions if text present ---
        _$('addressBar').on('focus', function () {
            var val = $(this).val().trim();
            if (val.length > 0) _filterAndShowSuggestions(val);
        });


        // --- Drag-and-drop: move files/folders within the tree ---
        // dragstart: record the dragged item
        _$('tree').on('dragstart', 'li', function (e) {
            var $li = $(this);
            state.dragSource = {
                path: $li.attr('data-path'),
                type: $li.attr('data-type'),
                name: $li.attr('data-name')
            };
            e.originalEvent.dataTransfer.effectAllowed = 'move';
            e.originalEvent.dataTransfer.setData('text/plain', state.dragSource.path);
            $li.addClass('fb-drag-source');
        });

        // dragend: clean up all visual state
        _$('tree').on('dragend', 'li', function () {
            state.dragSource = null;
            _$('tree').find('li').removeClass('fb-drag-over fb-drag-source');
        });

        // dragover: highlight valid folder targets
        _$('tree').on('dragover', 'li', function (e) {
            if (!state.dragSource) return;
            var $li = $(this);
            if ($li.attr('data-type') !== 'dir') return;
            if (!_isValidMoveTarget(state.dragSource.path, $li.attr('data-path'))) return;
            e.preventDefault();
            e.originalEvent.dataTransfer.dropEffect = 'move';
            _$('tree').find('li').removeClass('fb-drag-over');
            $li.addClass('fb-drag-over');
        });

        // dragleave: remove highlight when leaving a folder
        _$('tree').on('dragleave', 'li', function (e) {
            // Only remove if actually leaving the li (not entering a child)
            if (!$(e.relatedTarget).closest(this).length) {
                $(this).removeClass('fb-drag-over');
            }
        });

        // drop: execute the move
        _$('tree').on('drop', 'li', function (e) {
            e.preventDefault();
            e.stopPropagation();
            var $li = $(this);
            _$('tree').find('li').removeClass('fb-drag-over fb-drag-source');
            if (!state.dragSource) return;
            if ($li.attr('data-type') !== 'dir') return;
            var destDir = $li.attr('data-path');
            if (!_isValidMoveTarget(state.dragSource.path, destDir)) return;
            var srcPath = state.dragSource.path;
            var destPath = _joinPath(destDir, _basename(srcPath));
            state.dragSource = null;
            _moveItem(srcPath, destPath);
        });

        // --- Drag-and-drop onto the tree BACKGROUND = move to root ---
        // These fire only when the pointer is over the tree container itself,
        // not over any child <li> (those have stopPropagation on dragover/drop).
        _$('tree').on('dragover', function (e) {
            if (!state.dragSource) return;
            // Only handle background (not bubbled from a child li)
            if ($(e.target).closest('li').length) return;
            if (!_isValidMoveTarget(state.dragSource.path, '.')) return;
            e.preventDefault();
            e.originalEvent.dataTransfer.dropEffect = 'move';
            _$('tree').find('li').removeClass('fb-drag-over');
            _$('tree').addClass('fb-drag-over-root');
        });
        _$('tree').on('dragleave', function (e) {
            // Only clear if truly leaving the tree container
            if (!$(e.relatedTarget).closest('#' + _config.dom.tree).length) {
                _$('tree').removeClass('fb-drag-over-root');
            }
        });
        _$('tree').on('drop', function (e) {
            if ($(e.target).closest('li').length) return; // handled by li handler
            e.preventDefault();
            e.stopPropagation();
            _$('tree').removeClass('fb-drag-over-root');
            _$('tree').find('li').removeClass('fb-drag-over fb-drag-source');
            if (!state.dragSource) return;
            if (!_isValidMoveTarget(state.dragSource.path, '.')) return;
            var srcPath = state.dragSource.path;
            var destPath = _joinPath('.', _basename(srcPath));
            state.dragSource = null;
            _moveItem(srcPath, destPath);
        });


        // --- Tree click handlers (delegated) ---
        _$('tree').on('click', 'li', function (e) {
            e.stopPropagation();
            var $li = $(this);
            var type = $li.attr('data-type');
            var path = $li.attr('data-path');

            if (type === 'dir') {
                _toggleDir($li);
            } else {
                loadFile(path);
            }
            if (_config.onSelect) {
                _config.onSelect(path, type, { name: $li.attr('data-name'), type: type, path: path });
            }
        });

        // --- Context menu: right-click on tree items ---
        _$('tree').on('contextmenu', 'li', function (e) {
            e.preventDefault();
            e.stopPropagation();
            var $li = $(this);
            state.contextTarget = {
                path: $li.attr('data-path'),
                type: $li.attr('data-type'),
                name: $li.attr('data-name')
            };
            _showContextMenu(e.clientX, e.clientY);
        });

        // --- Context menu: right-click on tree background (create in current dir) ---
        _$('tree').on('contextmenu', function (e) {
            if ($(e.target).closest('li').length) return; // handled above
            e.preventDefault();
            state.contextTarget = { path: state.currentDir, type: 'dir', name: '' };
            _showContextMenu(e.clientX, e.clientY);
        });

        // --- Context menu actions ---
        _$('contextMenu').on('click', 'a[data-action]', function (e) {
            e.preventDefault();
            e.stopPropagation(); // Prevent document click handler from also firing
            var action = $(this).attr('data-action');
            // Save target before hiding (hide nulls state.contextTarget)
            var target = state.contextTarget;
            _hideContextMenu();
            state.contextTarget = target; // Restore for the action to use
            switch (action) {
                case 'new-file':   _createFile(); break;
                case 'new-folder': _createFolder(); break;
                case 'rename':     _renameItem(); break;
                case 'delete':     _deleteItem(); break;
                case 'move':
                    state.moveTarget = target;
                    _showMoveModal();
                    break;
            }
            state.contextTarget = null;
        });

        // --- Hide context menu on click outside ---
        $(document).on('click', function () {
            _hideContextMenu();
        });
        $(document).on('keydown', function (e) {
            if (e.key === 'Escape') {
                if (_$('contextMenu').is(':visible')) {
                    _hideContextMenu();
                    e.stopPropagation();
                }
            }
        });

        // --- Theme picker ---
        _$('themeSelect').on('change', function () {
            var newTheme = $(this).val();
            state.currentTheme = newTheme;
            if (state.cmEditor) {
                state.cmEditor.setOption('theme', newTheme);
            }
        });

        // --- View mode switching (Raw/Preview/WYSIWYG button group and select) ---
        _$('viewBtnGroup').on('click', '.btn', function () {
            var mode = $(this).attr('data-view');
            if (mode === state.viewMode) return;
            _setViewMode(mode);
        });

        _$('viewSelect').on('change', function () {
            var mode = $(this).val();
            if (mode === state.viewMode) return;
            _setViewMode(mode);
        });

        // --- Keyboard shortcuts (global, scoped to modal visibility) ---
        $(document).on('keydown', function (e) {
            if (!_$('modal').hasClass('show')) return;

            // Ctrl+S / Cmd+S → Save
            if ((e.ctrlKey || e.metaKey) && e.key === 's') {
                e.preventDefault();
                saveFile();
                return;
            }

            // Escape → Close modal (with dirty check)
            if (e.key === 'Escape') {
                // Don't close if context menu is visible (handled separately)
                if (_$('contextMenu').is(':visible')) return;
                e.preventDefault();
                _closeModal();
            }
        });

        // NOTE: hide.bs.modal won't fire because we bypass Bootstrap's modal JS.
        // Dirty check is handled in _closeModal() instead.
    }

    // ═══════════════════════════════════════════════════════════════
    //  Public API
    // ═══════════════════════════════════════════════════════════════

    return {
        /**
         * Initialize event handlers. Call once on page load.
         * @param {object} [cfg] - Config overrides (endpoints, dom, flags, callbacks).
         */
        init: init,
        /**
         * Open the file browser modal.
         * @param {string} [path] - Optional starting directory path.
         */
        open: open,
        loadFile: loadFile,
        saveFile: saveFile,
        discardChanges: discardChanges,
        /**
         * Override config options after initialization.
         * Deep-merges so partial endpoint/dom overrides don't wipe other keys.
         * @param {object} cfg - Config overrides.
         */
        configure: function (cfg) { $.extend(true, _config, cfg); }
    };

})();

// Initialize on DOM ready
$(document).ready(function () {
    FileBrowserManager.init();
});
