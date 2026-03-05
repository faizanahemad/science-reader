/**
 * Cross-Conversation Search Modal Manager.
 *
 * Entry point: magnifying glass icon in sidebar toolbar (#search-conversations-btn).
 * Opens a Bootstrap 4 modal with:
 *  - Debounced search input (500ms, min 5 chars)
 *  - Optional filters (workspace, flag, date range, deep search)
 *  - Result cards with title, snippet, date, workspace badge
 *  - Click-to-navigate: opens the matching conversation
 *
 * API: POST /search_conversations with action=search|list|summary.
 */
var CrossConversationSearchManager = (function () {
    'use strict';

    var _debounceTimer = null;
    var DEBOUNCE_MS = 500;
    var MIN_CHARS = 5;

    // ---------------------------------------------------------------
    // Init
    // ---------------------------------------------------------------

    function init() {
        // Search button in sidebar
        $(document).on('click', '#search-conversations-btn', function () {
            _showModal();
        });

        // Debounced keyup on search input
        $(document).on('keyup', '#cross-conv-search-input', function (e) {
            if (e.key === 'Enter' || e.keyCode === 13) {
                _onSearchSubmit();
            } else {
                _onSearchInputChange();
            }
        });

        // Clear button
        $(document).on('click', '#cross-conv-search-clear', function () {
            $('#cross-conv-search-input').val('').focus();
            _clearResults();
        });

        // Click on a search result
        $(document).on('click', '.cross-conv-result-item', function () {
            var convId = $(this).data('conversation-id');
            if (convId && window.ConversationManager) {
                $('#cross-conversation-search-modal').modal('hide');
                window.ConversationManager.setActiveConversation(convId);
            }
        });

        // Focus search input when modal opens
        $(document).on('shown.bs.modal', '#cross-conversation-search-modal', function () {
            $('#cross-conv-search-input').focus();
            _populateWorkspaceDropdown();
        });

        // Deep search checkbox and filter changes trigger re-search
        $(document).on('change', '#cross-conv-search-deep, #cross-conv-search-workspace, #cross-conv-search-flag, #cross-conv-search-date-from, #cross-conv-search-date-to', function () {
            _onSearchInputChange();
        });
    }

    // ---------------------------------------------------------------
    // Modal
    // ---------------------------------------------------------------

    function _showModal() {
        $('#cross-conversation-search-modal').modal('show');
    }

    // ---------------------------------------------------------------
    // Debounced search
    // ---------------------------------------------------------------

    function _onSearchInputChange() {
        clearTimeout(_debounceTimer);
        var query = ($('#cross-conv-search-input').val() || '').trim();

        if (query.length < MIN_CHARS) {
            _clearResults();
            return;
        }

        _debounceTimer = setTimeout(function () {
            _doSearch(query);
        }, DEBOUNCE_MS);
    }

    function _onSearchSubmit() {
        clearTimeout(_debounceTimer);
        var query = ($('#cross-conv-search-input').val() || '').trim();
        if (query.length > 0) {
            _doSearch(query);
        }
    }

    function _doSearch(query) {
        var filters = _getFilters();

        _showStatus('Searching...');
        _clearResults();

        $.ajax({
            url: '/search_conversations',
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({
                action: 'search',
                query: query,
                mode: 'keyword',
                deep: filters.deep,
                workspace_id: filters.workspace_id,
                flag: filters.flag,
                date_from: filters.date_from,
                date_to: filters.date_to,
                top_k: 30
            }),
            success: function (resp) {
                _hideStatus();
                if (resp && resp.results && resp.results.length > 0) {
                    _renderResults(resp.results, query);
                } else {
                    _showEmpty();
                }
            },
            error: function () {
                _hideStatus();
                _showEmpty();
            }
        });
    }

    // ---------------------------------------------------------------
    // Filters
    // ---------------------------------------------------------------

    function _getFilters() {
        return {
            deep: $('#cross-conv-search-deep').is(':checked'),
            workspace_id: $('#cross-conv-search-workspace').val() || '',
            flag: $('#cross-conv-search-flag').val() || '',
            date_from: $('#cross-conv-search-date-from').val() || '',
            date_to: $('#cross-conv-search-date-to').val() || ''
        };
    }

    function _populateWorkspaceDropdown() {
        var $sel = $('#cross-conv-search-workspace');
        // Only populate once
        if ($sel.data('populated')) return;

        var domain = (typeof currentDomain !== 'undefined' && currentDomain && currentDomain['domain'])
            ? currentDomain['domain'] : 'default';
        $.get('/list_workspaces/' + domain, function (data) {
            if (data && data.workspaces) {
                data.workspaces.forEach(function (ws) {
                    $sel.append(
                        $('<option></option>')
                            .val(ws.workspace_id)
                            .text(ws.workspace_name || ws.workspace_id)
                    );
                });
                $sel.data('populated', true);
            }
        }).fail(function () {
            // Workspace listing not available — leave as "All Workspaces"
        });
    }

    // ---------------------------------------------------------------
    // Rendering
    // ---------------------------------------------------------------

    function _renderResults(results, query) {
        var $container = $('#cross-conv-search-results');
        $container.empty();
        $('#cross-conv-search-empty').hide();

        results.forEach(function (r) {
            var snippet = r.match_snippet || '';
            var title = _escapeHtml(r.title || 'Untitled');
            var date = r.last_updated ? r.last_updated.substring(0, 10) : '';
            var msgCount = r.message_count || 0;
            var flag = r.flag && r.flag !== 'none' ? r.flag : '';

            var flagBadge = flag
                ? '<span class="badge mr-1" style="background-color:' + _flagColor(flag) + '; color:#fff;">' + flag + '</span>'
                : '';

            var html = [
                '<div class="cross-conv-result-item" data-conversation-id="' + _escapeHtml(r.conversation_id) + '">',
                '  <div class="d-flex justify-content-between align-items-start">',
                '    <div class="cross-conv-result-title">' + flagBadge + title + '</div>',
                '    <small class="text-muted text-nowrap ml-2">' + date + '</small>',
                '  </div>',
                '  <div class="cross-conv-result-snippet">' + snippet + '</div>',
                '  <div class="cross-conv-result-meta">',
                '    <small class="text-muted">' + msgCount + ' messages</small>',
                r.friendly_id ? '    <small class="text-muted ml-2">#' + _escapeHtml(r.friendly_id) + '</small>' : '',
                '  </div>',
                '</div>'
            ].join('\n');

            $container.append(html);
        });
    }

    function _flagColor(flag) {
        var colors = {
            red: '#dc3545', blue: '#007bff', green: '#28a745',
            yellow: '#ffc107', orange: '#fd7e14', purple: '#6f42c1'
        };
        return colors[flag] || '#6c757d';
    }

    function _escapeHtml(str) {
        if (!str) return '';
        return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    // ---------------------------------------------------------------
    // Status helpers
    // ---------------------------------------------------------------

    function _showStatus(msg) {
        $('#cross-conv-search-status-text').text(msg);
        $('#cross-conv-search-status').show();
    }

    function _hideStatus() {
        $('#cross-conv-search-status').hide();
    }

    function _clearResults() {
        $('#cross-conv-search-results').empty();
        $('#cross-conv-search-empty').hide();
    }

    function _showEmpty() {
        $('#cross-conv-search-results').empty();
        $('#cross-conv-search-empty').show();
    }

    // ---------------------------------------------------------------
    // Public API
    // ---------------------------------------------------------------

    return {
        init: init
    };

})();
