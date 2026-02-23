/**
 * Artefacts Manager
 *
 * Handles listing, viewing, editing, and LLM-assisted edit proposals
 * for conversation-scoped artefacts.
 */

var ArtefactsManager = (function () {
    'use strict';

    var state = {
        conversationId: null,
        artefacts: [],
        activeArtefactId: null,
        proposedOps: null,
        baseHash: null,
        diffText: '',
        diffHunks: [],
        selectedHunks: null,
        linkedMessage: null,
        pendingArtefact: null,
        pendingLinkLookup: null,
        linkMap: null,
        deepContext: false
    };

    function ensureLinksLoaded(onDone) {
        if (!state.conversationId) {
            if (typeof onDone === 'function') onDone();
            return;
        }
        fetch(`/artefacts/${state.conversationId}/message_links`)
            .then(r => r.json())
            .then(data => {
                state.linkMap = data && typeof data === 'object' ? data : {};
                if (typeof onDone === 'function') onDone();
            })
            .catch(err => {
                console.error(err);
                state.linkMap = {};
                if (typeof onDone === 'function') onDone();
            });
    }

    function setLinkedArtefact(conversationId, messageId, messageIndex, artefactId) {
        if (!conversationId || !messageId || !artefactId) return;
        fetch(`/artefacts/${conversationId}/message_links`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message_id: messageId,
                message_index: messageIndex,
                artefact_id: artefactId
            })
        })
            .then(r => r.json())
            .then(() => {
                if (!state.linkMap) {
                    state.linkMap = {};
                }
                state.linkMap[messageId] = {
                    artefact_id: artefactId,
                    message_index: messageIndex
                };
            })
            .catch(err => {
                console.error(err);
            });
    }

    function clearLinkedArtefact(conversationId, messageId) {
        if (!conversationId || !messageId) return;
        fetch(`/artefacts/${conversationId}/message_links/${messageId}`, {
            method: 'DELETE'
        })
            .then(() => {
                if (state.linkMap) {
                    delete state.linkMap[messageId];
                }
            })
            .catch(err => {
                console.error(err);
            });
    }

    function getLinkedArtefactId(conversationId, messageId) {
        if (!conversationId || !messageId || !state.linkMap) return null;
        var entry = state.linkMap[messageId];
        return entry ? entry.artefact_id : null;
    }

    function findLinkedMessageByArtefact(conversationId, artefactId) {
        if (!conversationId || !artefactId || !state.linkMap) return null;
        var messageIds = Object.keys(state.linkMap || {});
        for (var i = 0; i < messageIds.length; i++) {
            var msgId = messageIds[i];
            var entry = state.linkMap[msgId];
            if (entry && entry.artefact_id === artefactId) {
                return {
                    messageId: msgId,
                    messageIndex: entry.message_index
                };
            }
        }
        return null;
    }

    function buildLinkedMessage(conversationId, messageId, messageIndex) {
        var cardElem = null;
        var foundIndex = messageIndex;
        if (messageId) {
            var header = $(`[message-id="${messageId}"]`).closest('.card-header');
            if (header && header.length) {
                foundIndex = header.attr('message-index') || foundIndex;
                cardElem = header.closest('.card');
            }
        }
        return {
            messageId: messageId,
            messageIndex: foundIndex,
            cardElem: cardElem,
            artefactId: null,
            conversationId: conversationId
        };
    }

    function setProposeBusy(isBusy) {
        var button = $('#artefact-propose-btn');
        if (!button.length) return;
        if (button.data('default-html') === undefined) {
            button.data('default-html', button.html());
        }
        if (isBusy) {
            button.prop('disabled', true);
            button.html('<span class="spinner-border spinner-border-sm mr-2" role="status" aria-hidden="true"></span>Proposing...');
        } else {
            button.prop('disabled', false);
            button.html(button.data('default-html'));
        }
    }

    function init() {
        $('#artefacts-modal').on('shown.bs.modal', function () {
            ensureLinksLoaded(function () {
                if (state.pendingLinkLookup) {
                    var pending = state.pendingLinkLookup;
                    state.pendingLinkLookup = null;
                    state.activeArtefactId = null;
                    state.linkedMessage = buildLinkedMessage(state.conversationId, pending.messageId, pending.messageIndex);
                    state.linkedMessage.cardElem = pending.cardElem || state.linkedMessage.cardElem;
                    var existingArtefactId = getLinkedArtefactId(state.conversationId, pending.messageId);
                    if (existingArtefactId) {
                        setLinkedArtefact(state.conversationId, pending.messageId, pending.messageIndex, existingArtefactId);
                        state.linkedMessage.artefactId = existingArtefactId;
                        state.activeArtefactId = existingArtefactId;
                        state.pendingArtefact = null;
                    } else {
                        state.pendingArtefact = {
                            name: pending.defaultName,
                            fileType: pending.fileType,
                            content: pending.content
                        };
                    }
                }

                if (state.pendingArtefact) {
                    var pending = state.pendingArtefact;
                    state.pendingArtefact = null;
                    createArtefactWithContent(pending.name, pending.fileType, pending.content, function (artefactId) {
                        if (state.linkedMessage) {
                            state.linkedMessage.artefactId = artefactId;
                            setLinkedArtefact(state.conversationId, state.linkedMessage.messageId, state.linkedMessage.messageIndex, artefactId);
                        }
                        openArtefact(artefactId);
                    });
                } else {
                    loadList();
                }
            });
        });

        $('#artefacts-modal').on('hidden.bs.modal', function () {
            resetState();
        });

        $(document).off('click', '#artefact-create-btn').on('click', '#artefact-create-btn', createArtefact);
        $(document).off('click', '#artefacts-list .artefact-list-item').on('click', '#artefacts-list .artefact-list-item', function () {
            openArtefact($(this).data('id'));
            // Auto-close sidebar on mobile after selecting an artefact
            if (window.innerWidth < 768) {
                $('#artefacts-modal .artefact-sidebar').removeClass('show');
            }
        });
        $(document).off('click', '#artefact-save-btn').on('click', '#artefact-save-btn', saveArtefact);
        $(document).off('click', '#artefact-delete-btn').on('click', '#artefact-delete-btn', deleteArtefact);
        $(document).off('click', '#artefact-copy-btn').on('click', '#artefact-copy-btn', copyArtefact);
        $(document).off('click', '#artefact-download-btn').on('click', '#artefact-download-btn', downloadArtefact);
        $(document).off('click', '#artefact-propose-btn').on('click', '#artefact-propose-btn', proposeEdits);
        $(document).off('click', '#artefact-apply-btn').on('click', '#artefact-apply-btn', applyEdits);
        $(document).off('click', '#artefact-discard-btn').on('click', '#artefact-discard-btn', discardProposal);

        $(document).off('shown.bs.tab', '#artefact-preview-tab').on('shown.bs.tab', '#artefact-preview-tab', function () {
            renderPreview();
        });
        $(document).off('shown.bs.tab', '#artefact-diff-tab').on('shown.bs.tab', '#artefact-diff-tab', function () {
            renderDiff();
        });
        $(document).off('change', '.artefact-diff-hunk-toggle').on('change', '.artefact-diff-hunk-toggle', function () {
            var idx = parseInt($(this).data('hunk-index'), 10);
            if (!state.selectedHunks) {
                state.selectedHunks = {};
            }
            state.selectedHunks[idx] = $(this).is(':checked');
        });

        // Cmd+K overlay handlers
        $(document).off('click', '#art-ai-edit-cancel').on('click', '#art-ai-edit-cancel', _hideArtAiEditModal);
        $(document).off('click', '#art-ai-edit-generate').on('click', '#art-ai-edit-generate', _generateArtAiEdit);

        // Cmd+K / Ctrl+K keyboard shortcut on artefact textarea
        $(document).off('keydown', '#artefact-editor-textarea.art-cmdk').on('keydown', '#artefact-editor-textarea', function(e) {
            if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
                e.preventDefault();
                _showArtAiEditModal();
            }
        });

        // Escape to close AI edit overlay
        $(document).off('keydown.artAiEdit').on('keydown.artAiEdit', function(e) {
            if (e.key === 'Escape') {
                var modal = document.getElementById('artefact-ai-edit-modal');
                if (modal && modal.style.display === 'flex') {
                    e.stopPropagation();
                    _hideArtAiEditModal();
                    return;
                }
            }
        });

        // Ctrl+Enter / Cmd+Enter in instruction textarea
        $(document).off('keydown', '#art-ai-edit-instruction').on('keydown', '#art-ai-edit-instruction', function(e) {
            if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
                e.preventDefault();
                _generateArtAiEdit();
            }
        });

        // Backdrop click to close
        $(document).off('click', '#artefact-ai-edit-modal').on('click', '#artefact-ai-edit-modal', function(e) {
            if (e.target === this) _hideArtAiEditModal();
        });

        // Sidebar toggle for mobile
        $(document).off('click', '#artefact-sidebar-toggle').on('click', '#artefact-sidebar-toggle', function() {
            var sidebar = $('#artefacts-modal .artefact-sidebar');
            sidebar.toggleClass('show');
        });

        // Close sidebar when clicking outside it on mobile
        $('#artefacts-modal .modal-body').on('click', function(e) {
            var sidebar = $('#artefacts-modal .artefact-sidebar');
            if (sidebar.hasClass('show') && !$(e.target).closest('.artefact-sidebar').length) {
                sidebar.removeClass('show');
            }
        });
    }

    function resetState() {
        state.artefacts = [];
        state.activeArtefactId = null;
        state.proposedOps = null;
        state.baseHash = null;
        state.diffText = '';
        state.diffHunks = [];
        state.selectedHunks = null;
        state.linkedMessage = null;
        state.pendingArtefact = null;
        state.pendingLinkLookup = null;
        state.linkMap = null;
        setProposeBusy(false);
        $('#artefacts-list').empty();
        $('#artefact-editor-textarea').val('');
        $('#artefact-preview').empty();
        $('#artefact-diff').empty();
        $('#artefact-apply-btn').prop('disabled', true);
        $('#artefact-instruction').val('');
    }

    function getActiveConversationId() {
        if (typeof ConversationManager !== 'undefined' && ConversationManager.activeConversationId) {
            return ConversationManager.activeConversationId;
        }
        return '';
    }

    function openModal(conversationId) {
        state.conversationId = conversationId || getActiveConversationId();
        if (!state.conversationId) {
            showToast('No active conversation selected', 'error');
            return;
        }
        var settings = window.chatSettingsState || {};
        var historySetting = settings.history || ($('#settings-historySelector').val() || '2');
        var historyCount = historySetting === 'infinite' ? 50 : parseInt(historySetting, 10);
        if (isNaN(historyCount)) {
            historyCount = 10;
        }
        $('#artefact-history-count').val(historyCount);
        $('#artefact-include-messages').prop('checked', historyCount > 0);
        $('#artefact-include-summary').prop('checked', historySetting !== '-1');
        $('#artefact-include-memory').prop('checked', !!settings.use_memory_pad);
        $('#artefacts-modal').modal('show');
    }

    function openModalForMessage(conversationId, messageId, messageIndex, cardElem, messageText) {
        state.conversationId = conversationId || getActiveConversationId();
        if (!state.conversationId) {
            showToast('No active conversation selected', 'error');
            return;
        }
        var safeText = (messageText || '').toString();
        var cleanText = safeText.replace('<answer>', '').replace('</answer>', '').trim();
        var nameSuffix = messageId ? messageId.toString().slice(0, 8) : 'answer';
        var defaultName = 'Answer ' + nameSuffix;
        state.activeArtefactId = null;
        state.pendingLinkLookup = {
            messageId: messageId,
            messageIndex: messageIndex,
            cardElem: cardElem,
            defaultName: defaultName,
            fileType: 'md',
            content: cleanText
        };
        state.pendingArtefact = null;
        openModal(state.conversationId);
    }

    function loadList() {
        if (!state.conversationId) return;
        fetch(`/artefacts/${state.conversationId}`)
            .then(r => r.json())
            .then(data => {
                state.artefacts = Array.isArray(data) ? data : [];
                renderList();
                if (state.activeArtefactId) {
                    openArtefact(state.activeArtefactId);
                } else if (state.artefacts.length > 0) {
                    openArtefact(state.artefacts[0].id);
                }
            })
            .catch(err => {
                console.error(err);
                showToast('Failed to load artefacts', 'error');
            });
    }

    function renderList() {
        var list = $('#artefacts-list');
        list.empty();
        if (!state.artefacts.length) {
            list.append('<div class="text-muted small p-2">No artefacts yet</div>');
            return;
        }
        state.artefacts.forEach(function (artefact, index) {
            var label = artefact.name || artefact.file_name || ('Artefact ' + (index + 1));
            var type = artefact.file_type ? ('.' + artefact.file_type) : '';
            var item = $(
                `<button type="button" class="list-group-item list-group-item-action artefact-list-item" data-id="${artefact.id}">
                    <div class="d-flex justify-content-between align-items-center">
                        <span>${label}</span>
                        <small class="text-muted">${type}</small>
                    </div>
                </button>`
            );
            if (artefact.id === state.activeArtefactId) {
                item.addClass('active');
            }
            list.append(item);
        });
    }

    function openArtefact(artefactId) {
        if (!artefactId || !state.conversationId) return;
        fetch(`/artefacts/${state.conversationId}/${artefactId}`)
            .then(r => r.json())
            .then(data => {
                state.activeArtefactId = artefactId;
                $('#artefact-editor-textarea').val(data.content || '');
                if (data.file_type) {
                    $('#artefact-file-type').val(data.file_type);
                }
                var linked = findLinkedMessageByArtefact(state.conversationId, artefactId);
                if (linked && linked.messageId) {
                    state.linkedMessage = buildLinkedMessage(state.conversationId, linked.messageId, linked.messageIndex);
                    state.linkedMessage.artefactId = artefactId;
                } else {
                    state.linkedMessage = null;
                }
                discardProposal();
                renderList();
            })
            .catch(err => {
                console.error(err);
                showToast('Failed to open artefact', 'error');
            });
    }

    function createArtefact() {
        if (!state.conversationId) return;
        var name = window.prompt('Artefact name');
        if (name === null) return;
        var fileType = $('#artefact-file-type').val() || 'txt';
        createArtefactWithContent(name, fileType, '', function (artefactId) {
            openArtefact(artefactId);
        });
    }

    function createArtefactWithContent(name, fileType, content, onSuccess) {
        if (!state.conversationId) return;
        fetch(`/artefacts/${state.conversationId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: name, file_type: fileType, initial_content: content || '' })
        })
            .then(r => r.json())
            .then(data => {
                showToast('Artefact created', 'success');
                loadList();
                if (data && data.id) {
                    if (typeof onSuccess === 'function') {
                        onSuccess(data.id);
                    }
                }
            })
            .catch(err => {
                console.error(err);
                showToast('Failed to create artefact', 'error');
            });
    }

    function saveArtefact() {
        if (!state.activeArtefactId || !state.conversationId) {
            showToast('Select or create an artefact first', 'warning');
            return;
        }
        var content = $('#artefact-editor-textarea').val() || '';
        fetch(`/artefacts/${state.conversationId}/${state.activeArtefactId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ content: content })
        })
            .then(r => r.json())
            .then(() => {
                showToast('Artefact saved', 'success');
                loadList();
                if (
                    state.linkedMessage &&
                    state.linkedMessage.artefactId &&
                    state.linkedMessage.artefactId === state.activeArtefactId
                ) {
                    var linkedMessageId = state.linkedMessage.messageId;
                    var linkedIndex = state.linkedMessage.messageIndex;
                    var linkedCard = state.linkedMessage.cardElem;
                    if (linkedMessageId && linkedIndex === undefined) {
                        var header = $(`[message-id="${linkedMessageId}"]`).closest('.card-header');
                        if (header && header.length) {
                            linkedIndex = header.attr('message-index');
                            linkedCard = header.closest('.card');
                        }
                    }
                    if (linkedCard && linkedCard.length) {
                        ConversationManager.saveMessageEditText(
                            content,
                            linkedMessageId,
                            linkedIndex,
                            linkedCard
                        );
                    } else if (linkedMessageId && linkedIndex !== undefined) {
                        $.ajax({
                            url: '/edit_message_from_conversation/' + state.conversationId + '/' + linkedMessageId + '/' + linkedIndex,
                            type: 'POST',
                            contentType: 'application/json',
                            data: JSON.stringify({ 'text': content })
                        }).fail(function (result) {
                            alert('Error: ' + result.responseText);
                        });
                    }
                }
            })
            .catch(err => {
                console.error(err);
                showToast('Failed to save artefact', 'error');
            });
    }

    function deleteArtefact() {
        if (!state.activeArtefactId || !state.conversationId) {
            showToast('Select or create an artefact first', 'warning');
            return;
        }
        if (!confirm('Delete this artefact?')) return;
        fetch(`/artefacts/${state.conversationId}/${state.activeArtefactId}`, {
            method: 'DELETE'
        })
            .then(r => r.json())
            .then(() => {
                showToast('Artefact deleted', 'success');
                if (state.linkedMessage && state.linkedMessage.artefactId === state.activeArtefactId) {
                    clearLinkedArtefact(state.conversationId, state.linkedMessage.messageId);
                    state.linkedMessage = null;
                }
                state.activeArtefactId = null;
                $('#artefact-editor-textarea').val('');
                loadList();
            })
            .catch(err => {
                console.error(err);
                showToast('Failed to delete artefact', 'error');
            });
    }

    function copyArtefact() {
        var content = $('#artefact-editor-textarea').val() || '';
        if (!content) return;
        navigator.clipboard.writeText(content)
            .then(() => showToast('Artefact copied', 'success'))
            .catch(() => showToast('Failed to copy artefact', 'error'));
    }

    function downloadArtefact() {
        if (!state.activeArtefactId || !state.conversationId) {
            showToast('Select an artefact first', 'warning');
            return;
        }
        window.location = `/artefacts/${state.conversationId}/${state.activeArtefactId}/download`;
    }

    function getSelectionLines() {
        var textarea = document.getElementById('artefact-editor-textarea');
        if (!textarea) return null;
        var start = textarea.selectionStart;
        var end = textarea.selectionEnd;
        if (start === end) return null;
        var beforeStart = textarea.value.slice(0, start);
        var beforeEnd = textarea.value.slice(0, end);
        var startLine = beforeStart.split('\n').length;
        var endLine = beforeEnd.split('\n').length;
        return { start_line: startLine, end_line: endLine };
    }

    function proposeEdits() {
        if (!state.activeArtefactId || !state.conversationId) {
            showToast('Select or create an artefact first', 'warning');
            return;
        }
        var instruction = ($('#artefact-instruction').val() || '').trim();
        if (!instruction) {
            showToast('Add an instruction first', 'error');
            return;
        }
        setProposeBusy(true);
        var selection = getSelectionLines();
        var payload = {
            instruction: instruction,
            selection: selection,
            include_summary: $('#artefact-include-summary').is(':checked'),
            include_messages: $('#artefact-include-messages').is(':checked'),
            include_memory_pad: $('#artefact-include-memory').is(':checked'),
            history_count: parseInt($('#artefact-history-count').val() || '10', 10),
            deep_context: state.deepContext || false
        };
        state.deepContext = false;
        fetch(`/artefacts/${state.conversationId}/${state.activeArtefactId}/propose_edits`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        })
            .then(r => r.json())
            .then(data => {
                if (data.status === 'error') {
                    showToast(data.message || 'Failed to propose edits', 'error');
                    setProposeBusy(false);
                    return;
                }
                state.proposedOps = data.proposed_ops || [];
                state.baseHash = data.base_hash || null;
                state.diffText = data.diff_text || '';
                state.diffHunks = parseUnifiedDiff(state.diffText);
                state.selectedHunks = {};
        state.diffHunks.forEach(function (_hunk, idx) {
            state.selectedHunks[idx] = true;
        });
                renderDiff();
                $('#artefact-apply-btn').prop('disabled', !state.diffText);
                $('#artefact-diff-tab').tab('show');
                setProposeBusy(false);
            })
            .catch(err => {
                console.error(err);
                showToast('Failed to propose edits', 'error');
                setProposeBusy(false);
            });
    }

    function applyOpsToContent(content, ops) {
        var updated = content || '';
        if (!ops || !ops.length) {
            return updated;
        }
        ops.forEach(function (op) {
            var type = op.op;
            if (type === 'replace_range') {
                updated = replaceRange(updated, op.start_line, op.end_line, op.text || '');
            } else if (type === 'insert_at') {
                updated = insertAt(updated, op.start_line, op.text || '');
            } else if (type === 'append') {
                updated = appendText(updated, op.text || '');
            } else if (type === 'delete_range') {
                updated = deleteRange(updated, op.start_line, op.end_line);
            }
        });
        return updated;
    }

    function replaceRange(content, startLine, endLine, text) {
        var lines = (content || '').split('\n');
        var startIdx = Math.max(1, parseInt(startLine || 1, 10)) - 1;
        var endIdx = Math.max(startIdx, parseInt(endLine || startIdx + 1, 10) - 1);
        endIdx = Math.min(endIdx, lines.length - 1);
        var newLines = (text || '').split('\n');
        if (startIdx > lines.length) {
            lines = lines.concat(newLines);
        } else {
            if (endIdx < startIdx) {
                endIdx = startIdx - 1;
            }
            lines.splice.apply(lines, [startIdx, endIdx - startIdx + 1].concat(newLines));
        }
        return lines.join('\n');
    }

    function insertAt(content, line, text) {
        var lines = (content || '').split('\n');
        var insertIdx = Math.max(1, parseInt(line || 1, 10)) - 1;
        insertIdx = Math.min(insertIdx, lines.length);
        var newLines = (text || '').split('\n');
        lines.splice.apply(lines, [insertIdx, 0].concat(newLines));
        return lines.join('\n');
    }

    function appendText(content, text) {
        if (!content) {
            return text || '';
        }
        if (text && !content.endsWith('\n')) {
            return content + '\n' + text;
        }
        return content + (text || '');
    }

    function deleteRange(content, startLine, endLine) {
        var lines = (content || '').split('\n');
        if (!lines.length) {
            return '';
        }
        var startIdx = Math.max(1, parseInt(startLine || 1, 10)) - 1;
        var endIdx = Math.max(startIdx, parseInt(endLine || startIdx + 1, 10) - 1);
        endIdx = Math.min(endIdx, lines.length - 1);
        lines.splice(startIdx, endIdx - startIdx + 1);
        return lines.join('\n');
    }

    function applyEdits() {
        if (!state.proposedOps || !state.proposedOps.length) {
            showToast('No proposed edits to apply', 'warning');
            return;
        }
        var current = $('#artefact-editor-textarea').val() || '';
        var opsToApply = filterOpsForSelectedHunks(current, state.proposedOps);
        if (!opsToApply.length) {
            showToast('No selected diff hunks to apply', 'warning');
            return;
        }
        var updated = applyOpsToContent(current, opsToApply);
        $('#artefact-editor-textarea').val(updated);
        discardProposal(false);
        showToast('Edits applied in editor. Click Save to persist.', 'success');
        renderPreview();
        $('#artefact-code-tab').tab('show');
    }

    function discardProposal(clearDiff = true) {
        state.proposedOps = null;
        state.baseHash = null;
        if (clearDiff) {
            state.diffText = '';
            state.diffHunks = [];
            state.selectedHunks = null;
            $('#artefact-diff').empty();
        }
        $('#artefact-apply-btn').prop('disabled', true);
    }

    function renderPreview() {
        var content = $('#artefact-editor-textarea').val() || '';
        var preview = document.getElementById('artefact-preview');
        if (!preview) return;
        if (typeof marked !== 'undefined') {
            preview.innerHTML = marked.parse(content);
        } else {
            preview.textContent = content;
        }
        $('#artefact-preview pre code').each(function () {
            if (typeof hljs !== 'undefined') {
                hljs.highlightElement(this);
            }
        });
    }

    function renderDiff() {
        var container = $('#artefact-diff');
        container.empty();
        if (!state.diffText) {
            return;
        }
        if (!state.diffHunks || !state.diffHunks.length) {
            container.text(state.diffText);
            return;
        }
        var headerLines = state.diffHunks._headers || [];
        headerLines.forEach(function (line) {
            container.append(buildDiffLine(line, 'artefact-diff-line artefact-diff-header'));
        });
        state.diffHunks.forEach(function (hunk, idx) {
            var isChecked = !state.selectedHunks || state.selectedHunks[idx] !== false;
            var headerEl = document.createElement('div');
            headerEl.className = 'artefact-diff-line artefact-diff-hunk';
            headerEl.innerHTML = `<label class="mb-0 d-flex align-items-center">
                <input type="checkbox" class="artefact-diff-hunk-toggle" data-hunk-index="${idx}" ${isChecked ? 'checked' : ''}>
                <span>${escapeHtml(hunk.header)}</span>
            </label>`;
            container.append(headerEl);
            hunk.lines.forEach(function (line) {
                var cls = 'artefact-diff-line';
                if (line.startsWith('+') && !line.startsWith('+++')) {
                    cls += ' artefact-diff-add';
                } else if (line.startsWith('-') && !line.startsWith('---')) {
                    cls += ' artefact-diff-del';
                } else if (line.startsWith('@@')) {
                    cls += ' artefact-diff-hunk';
                } else if (line.startsWith('---') || line.startsWith('+++')) {
                    cls += ' artefact-diff-header';
                }
                container.append(buildDiffLine(line, cls));
            });
        });
    }

    function buildDiffLine(line, cls) {
        var el = document.createElement('div');
        el.className = cls;
        el.textContent = line || '';
        return el;
    }

    function escapeHtml(value) {
        return (value || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    function parseUnifiedDiff(diffText) {
        var lines = (diffText || '').split('\n');
        var hunks = [];
        var headers = [];
        var current = null;
        lines.forEach(function (line) {
            if (line.startsWith('@@')) {
                if (current) {
                    hunks.push(current);
                }
                var parsed = parseHunkHeader(line);
                current = {
                    header: line,
                    lines: [],
                    newStart: parsed.newStart,
                    newLen: parsed.newLen
                };
                return;
            }
            if (!current) {
                headers.push(line);
            } else {
                current.lines.push(line);
            }
        });
        if (current) {
            hunks.push(current);
        }
        var blocks = splitDiffHunksIntoBlocks(hunks);
        blocks._headers = headers;
        return blocks;
    }

    function splitDiffHunksIntoBlocks(hunks) {
        var blocks = [];
        var contextWindow = 2;
        (hunks || []).forEach(function (hunk, hunkIndex) {
            var lineNewPositions = [];
            var newLine = hunk.newStart || 1;
            hunk.lines.forEach(function (line, idx) {
                var isAdd = line.startsWith('+') && !line.startsWith('+++');
                var isDel = line.startsWith('-') && !line.startsWith('---');
                var isContext = !isAdd && !isDel;
                lineNewPositions[idx] = newLine;
                if (isAdd || isContext) {
                    newLine += 1;
                }
            });

            var changeIndices = [];
            hunk.lines.forEach(function (line, idx) {
                var isAdd = line.startsWith('+') && !line.startsWith('+++');
                var isDel = line.startsWith('-') && !line.startsWith('---');
                if (isAdd || isDel) {
                    changeIndices.push(idx);
                }
            });

            if (!changeIndices.length) {
                blocks.push({
                    header: hunk.header,
                    lines: hunk.lines,
                    newStart: hunk.newStart,
                    newLen: hunk.newLen || 1,
                    hunkIndex: hunkIndex,
                    blockIndex: 0
                });
                return;
            }

            var windows = changeIndices.map(function (idx) {
                return {
                    start: Math.max(0, idx - contextWindow),
                    end: Math.min(hunk.lines.length - 1, idx + contextWindow)
                };
            });
            windows.sort(function (a, b) { return a.start - b.start; });
            var merged = [];
            windows.forEach(function (win) {
                if (!merged.length) {
                    merged.push({ start: win.start, end: win.end });
                    return;
                }
                var last = merged[merged.length - 1];
                if (win.start <= last.end + 1) {
                    last.end = Math.max(last.end, win.end);
                } else {
                    merged.push({ start: win.start, end: win.end });
                }
            });

            merged.forEach(function (win, blockIndex) {
                var blockLines = hunk.lines.slice(win.start, win.end + 1);
                var rangeLines = [];
                for (var i = win.start; i <= win.end; i++) {
                    rangeLines.push(lineNewPositions[i]);
                }
                var start = rangeLines.length ? Math.min.apply(null, rangeLines) : (hunk.newStart || 1);
                var end = rangeLines.length ? Math.max.apply(null, rangeLines) : start;
                var length = Math.max(1, end - start + 1);
                blocks.push({
                    header: hunk.header + ' (block ' + (blockIndex + 1) + ')',
                    lines: blockLines,
                    newStart: start,
                    newLen: length,
                    hunkIndex: hunkIndex,
                    blockIndex: blockIndex
                });
            });
        });
        return blocks;
    }

    function parseHunkHeader(header) {
        var match = header.match(/\+(\d+)(?:,(\d+))?/);
        var newStart = match ? parseInt(match[1], 10) : 1;
        var newLen = match && match[2] ? parseInt(match[2], 10) : 1;
        return { newStart: newStart, newLen: newLen };
    }

    function filterOpsForSelectedHunks(content, ops) {
        if (!state.diffHunks || !state.diffHunks.length || !state.selectedHunks) {
            return ops;
        }
        var selectedRanges = [];
        state.diffHunks.forEach(function (hunk, idx) {
            if (state.selectedHunks[idx]) {
                var start = hunk.newStart;
                var len = hunk.newLen || 1;
                var end = start + Math.max(len, 1) - 1;
                selectedRanges.push({ start: start, end: end });
            }
        });
        if (!selectedRanges.length) {
            return [];
        }
        var currentLineCount = (content || '').split('\n').length;
        return ops.filter(function (op) {
            var range = getOpRange(op, currentLineCount);
            if (!range) {
                return true;
            }
            return selectedRanges.some(function (sel) {
                return range.start <= sel.end && range.end >= sel.start;
            });
        });
    }

    function getOpRange(op, currentLineCount) {
        if (!op || !op.op) {
            return null;
        }
        if (op.op === 'replace_range' || op.op === 'delete_range') {
            return { start: parseInt(op.start_line || 1, 10), end: parseInt(op.end_line || op.start_line || 1, 10) };
        }
        if (op.op === 'insert_at') {
            var line = parseInt(op.start_line || 1, 10);
            return { start: line, end: line };
        }
        if (op.op === 'append') {
            var endLine = Math.max(1, currentLineCount + 1);
            return { start: endLine, end: endLine };
        }
        return null;
    }

    function _showArtAiEditModal() {
        var textarea = document.getElementById('artefact-editor-textarea');
        if (!textarea) {
            showToast('No artefact open', 'warning');
            return;
        }

        var start = textarea.selectionStart;
        var end = textarea.selectionEnd;
        if (start !== end) {
            var beforeStart = textarea.value.slice(0, start);
            var beforeEnd = textarea.value.slice(0, end);
            var startLine = beforeStart.split('\n').length;
            var endLine = beforeEnd.split('\n').length;
            $('#art-ai-edit-info').text('Editing: lines ' + startLine + '-' + endLine + ' (selected)');
        } else {
            $('#art-ai-edit-info').text('Editing: entire artefact');
        }


        // Initialize modal controls from footer state
        $('#art-ai-edit-include-summary').prop('checked', $('#artefact-include-summary').is(':checked'));
        $('#art-ai-edit-include-messages').prop('checked', $('#artefact-include-messages').is(':checked'));
        $('#art-ai-edit-include-memory').prop('checked', $('#artefact-include-memory').is(':checked'));
        $('#art-ai-edit-history-count').val($('#artefact-history-count').val());
        $('#art-ai-edit-deep-context').prop('checked', false);

        var modal = document.getElementById('artefact-ai-edit-modal');
        modal.style.display = 'flex';
        setTimeout(function() {
            $('#art-ai-edit-instruction').focus();
        }, 50);
    }

    function _hideArtAiEditModal() {
        var modal = document.getElementById('artefact-ai-edit-modal');
        modal.style.display = 'none';
        $('#art-ai-edit-spinner').hide();
        $('#art-ai-edit-generate').prop('disabled', false);
    }

    function _generateArtAiEdit() {
        var instruction = ($('#art-ai-edit-instruction').val() || '').trim();
        if (!instruction) {
            showToast('Please enter an instruction', 'warning');
            return;
        }

        // Put instruction into existing propose edits textarea
        $('#artefact-instruction').val(instruction);
        // Sync AI edit modal controls to footer controls
        $('#artefact-include-summary').prop('checked', $('#art-ai-edit-include-summary').is(':checked'));
        $('#artefact-include-messages').prop('checked', $('#art-ai-edit-include-messages').is(':checked'));
        $('#artefact-include-memory').prop('checked', $('#art-ai-edit-include-memory').is(':checked'));
        $('#artefact-history-count').val($('#art-ai-edit-history-count').val());
        // Set deep_context flag on state
        state.deepContext = $('#art-ai-edit-deep-context').is(':checked');
        _hideArtAiEditModal();
        // Call existing proposeEdits function
        proposeEdits();
    }
    init();

    return {
        openModal: openModal,
        openModalForMessage: openModalForMessage
    };
})();
