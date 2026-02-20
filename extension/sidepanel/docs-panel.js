/**
 * DocsPanel — Overlay panel for managing conversation documents and global documents.
 *
 * Two collapsible sections: Conversation Documents (scoped to active conversation)
 * and Global Documents (user-wide). Each supports list, upload, download, remove.
 *
 * Depends on: API (from shared/api.js) available as global via sidepanel.js import.
 */

var DocsPanel = (function() {
    var _conversationId = null;

    function init() {
        document.querySelectorAll('#docs-panel .section-header[data-toggle]').forEach(function(header) {
            header.addEventListener('click', function() {
                var targetId = this.getAttribute('data-toggle');
                var body = document.getElementById(targetId);
                var arrow = this.querySelector('.collapse-arrow');
                body.classList.toggle('hidden');
                arrow.textContent = body.classList.contains('hidden') ? '\u25b8' : '\u25be';
            });
        });
        _wireUploadButton('conv-doc-upload-btn', 'conv-doc-upload', _uploadConvDoc);
        _wireUploadButton('global-doc-upload-btn', 'global-doc-upload', _uploadGlobalDoc);
    }

    function setConversation(conversationId) {
        _conversationId = conversationId;
        if (!document.getElementById('docs-panel').classList.contains('hidden')) {
            loadConversationDocs();
        }
    }

    async function loadConversationDocs() {
        if (!_conversationId) {
            _renderDocItems('conv-docs-items', [], 'conv-doc-count');
            return;
        }
        try {
            var docs = await API.listDocuments(_conversationId);
            if (!Array.isArray(docs)) docs = [];
            _renderDocItems('conv-docs-items', docs, 'conv-doc-count', {
                onDownload: function(doc) { _downloadConvDoc(doc); },
                onRemove: function(doc) { _removeConvDoc(doc); }
            });
        } catch (err) {
            console.error('[DocsPanel] Failed to load conversation docs:', err);
        }
    }

    async function loadGlobalDocs() {
        try {
            var result = await API.listGlobalDocs();
            var docs = Array.isArray(result) ? result : (result.docs || []);
            _renderDocItems('global-docs-items', docs, 'global-doc-count', {
                onDownload: function(doc) { _downloadGlobalDoc(doc); },
                onRemove: function(doc) { _removeGlobalDoc(doc); }
            });
        } catch (err) {
            console.error('[DocsPanel] Failed to load global docs:', err);
        }
    }

    function _renderDocItems(containerId, docs, countId, actions) {
        var container = document.getElementById(containerId);
        var countEl = document.getElementById(countId);
        if (countEl) countEl.textContent = '(' + docs.length + ')';
        if (!container) return;

        if (docs.length === 0) {
            container.innerHTML = '<div class="doc-empty">No documents</div>';
            return;
        }
        container.innerHTML = docs.map(function(doc, idx) {
            var title = doc.title || doc.display_name || doc.source || 'Document';
            var ref = doc.doc_id ? '#doc_' + (idx + 1) : '';
            return '<div class="doc-item" data-doc-id="' + (doc.doc_id || '') + '">' +
                '<div class="doc-info">' +
                    '<span class="doc-title" title="' + title + '">' + title + '</span>' +
                    (ref ? '<span class="doc-ref">' + ref + '</span>' : '') +
                '</div>' +
                '<div class="doc-actions">' +
                    '<button class="doc-action-btn doc-download" title="Download">\u2b07</button>' +
                    '<button class="doc-action-btn doc-remove" title="Remove">\ud83d\uddd1</button>' +
                '</div>' +
            '</div>';
        }).join('');

        if (actions) {
            container.querySelectorAll('.doc-download').forEach(function(btn, i) {
                btn.addEventListener('click', function() { actions.onDownload(docs[i]); });
            });
            container.querySelectorAll('.doc-remove').forEach(function(btn, i) {
                btn.addEventListener('click', function() { actions.onRemove(docs[i]); });
            });
        }
    }

    async function _uploadConvDoc(file) {
        if (!_conversationId) return;
        try {
            var formData = new FormData();
            formData.append('pdf_file', file);
            await API.uploadDoc(_conversationId, formData);
            loadConversationDocs();
        } catch (err) {
            console.error('[DocsPanel] Conv doc upload failed:', err);
        }
    }

    async function _uploadGlobalDoc(file) {
        try {
            var formData = new FormData();
            formData.append('pdf_file', file);
            formData.append('display_name', file.name);
            await API.uploadGlobalDoc(formData);
            loadGlobalDocs();
        } catch (err) {
            console.error('[DocsPanel] Global doc upload failed:', err);
        }
    }

    async function _downloadConvDoc(doc) {
        var url = await API.downloadDocUrl(_conversationId, doc.doc_id);
        window.open(url, '_blank');
    }

    async function _downloadGlobalDoc(doc) {
        var url = await API.downloadGlobalDocUrl(doc.doc_id);
        window.open(url, '_blank');
    }

    async function _removeConvDoc(doc) {
        if (!confirm('Remove "' + (doc.title || 'document') + '" from conversation?')) return;
        try {
            await API.deleteDocument(_conversationId, doc.doc_id);
            loadConversationDocs();
        } catch (err) {
            console.error('[DocsPanel] Remove conv doc failed:', err);
        }
    }

    async function _removeGlobalDoc(doc) {
        if (!confirm('Delete global doc "' + (doc.title || doc.display_name || 'document') + '"?')) return;
        try {
            await API.deleteGlobalDoc(doc.doc_id);
            loadGlobalDocs();
        } catch (err) {
            console.error('[DocsPanel] Remove global doc failed:', err);
        }
    }

    function _wireUploadButton(btnId, inputId, handler) {
        var btn = document.getElementById(btnId);
        var input = document.getElementById(inputId);
        if (btn && input) {
            btn.addEventListener('click', function() { input.click(); });
            input.addEventListener('change', function() {
                if (this.files.length > 0) { handler(this.files[0]); this.value = ''; }
            });
        }
    }

    function show() {
        document.getElementById('docs-panel').classList.remove('hidden');
        loadConversationDocs();
        loadGlobalDocs();
    }

    function hide() {
        document.getElementById('docs-panel').classList.add('hidden');
    }

    function toggle() {
        var panel = document.getElementById('docs-panel');
        if (panel.classList.contains('hidden')) { show(); } else { hide(); }
    }

    return {
        init: init,
        show: show,
        hide: hide,
        toggle: toggle,
        setConversation: setConversation,
        loadConversationDocs: loadConversationDocs,
        loadGlobalDocs: loadGlobalDocs
    };
})();
