/**
 * ToolCallManager
 * ---------------
 * UI manager for mid-stream LLM tool call interactions.
 *
 * When the LLM invokes a tool during its streaming response, this manager:
 * - For interactive tools (ask_clarification): shows a Bootstrap modal with questions,
 *   collects user input, and POSTs it back to the server.
 * - For server-side tools (web_search, document_lookup): shows an inline status indicator
 *   in the streaming chat area.
 *
 * This is separate from ClarificationsManager which handles PRE-SEND clarifications
 * via the /clarify slash command. ToolCallManager handles MID-RESPONSE tool calls
 * that occur while the LLM is actively generating a reply.
 *
 * Design principles:
 * - Fail-open: any error should let the LLM continue without blocking.
 * - Minimal UI footprint: inline status pills for server-side tools, modal only
 *   for interactive tools that need user input.
 * - Single modal at a time: only one interactive tool call modal can be open.
 * - Consistent styling with the existing clarifications modal.
 *
 * Called by: renderStreamingResponse() in common-chat.js
 * Endpoint:  POST /tool_response/{conversation_id}/{tool_id}
 */
(function () {
    'use strict';

    /* ──────────────────────────────────────────────
     * Inline styles — injected once on first load.
     * Keeps tool-call UI consistent without touching
     * external stylesheets.
     * ────────────────────────────────────────────── */
    var STYLE_ID = 'tool-call-manager-styles';

    function _injectStyles() {
        if (document.getElementById(STYLE_ID)) return;
        var css = [
            /* ── Status indicator pill (inline in chat stream) ── */
            '.tool-call-status {',
            '    display: inline-flex;',
            '    align-items: center;',
            '    gap: 6px;',
            '    padding: 4px 12px;',
            '    margin: 6px 0;',
            '    border-radius: 16px;',
            '    font-size: 0.82rem;',
            '    font-weight: 500;',
            '    color: #495057;',
            '    background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%);',
            '    border: 1px solid #dee2e6;',
            '    transition: all 0.3s ease;',
            '    animation: toolStatusFadeIn 0.35s ease-out;',
            '}',
            '.tool-call-status.completed {',
            '    color: #155724;',
            '    background: linear-gradient(135deg, #d4edda 0%, #c3e6cb 100%);',
            '    border-color: #b1dfbb;',
            '}',
            '.tool-call-status.error {',
            '    color: #721c24;',
            '    background: linear-gradient(135deg, #f8d7da 0%, #f5c6cb 100%);',
            '    border-color: #f1b0b7;',
            '}',
            '.tool-call-status .status-icon {',
            '    font-size: 0.9rem;',
            '}',
            '.tool-call-status .status-text {',
            '    white-space: nowrap;',
            '}',
            '@keyframes toolStatusFadeIn {',
            '    from { opacity: 0; transform: translateY(4px); }',
            '    to   { opacity: 1; transform: translateY(0); }',
            '}',
            '',
            /* ── Fade-out for completed indicators ── */
            '.tool-call-status.fade-out {',
            '    opacity: 0;',
            '    transition: opacity 0.6s ease;',
            '}',
            '',
            /* ── Modal question styling ── */
            '.tool-call-question {',
            '    margin-bottom: 1rem;',
            '}',
            '.tool-call-question .question-label {',
            '    font-size: 0.98rem;',
            '    font-weight: 600;',
            '    margin-bottom: 0.35rem;',
            '    color: #333;',
            '}',
            '.tool-call-question .form-check {',
            '    padding-top: 2px;',
            '    padding-bottom: 2px;',
            '}',
            '.tool-call-question .form-check-label {',
            '    font-size: 0.95rem;',
            '    cursor: pointer;',
            '}',
            '',
            /* ── Submit button loading state ── */
            '#tool-call-submit-btn.loading {',
            '    pointer-events: none;',
            '    opacity: 0.7;',
            '}'
        ].join('\n');

        var style = document.createElement('style');
        style.id = STYLE_ID;
        style.textContent = css;
        document.head.appendChild(style);
    }

    /* ──────────────────────────────────────────────
     * Utility helpers
     * ────────────────────────────────────────────── */

    function _escapeHtml(text) {
        var div = document.createElement('div');
        div.textContent = (text == null) ? '' : String(text);
        return div.innerHTML;
    }

    function _showToastOrAlert(message, level) {
        if (typeof showToast === 'function') {
            showToast(message, level || 'info');
            return;
        }
        alert(message);
    }

    /* ──────────────────────────────────────────────
     * Status messages per tool + status combination.
     * ────────────────────────────────────────────── */
    var STATUS_MESSAGES = {
        'ask_clarification': {
            'calling':          'Preparing clarification questions…',
            'executing':        'Preparing clarification questions…',
            'waiting_for_user': 'Waiting for your response…',
            'completed':        'Clarification received',
            'error':            'Clarification failed'
        },
        'web_search': {
            'calling':    'Searching the web…',
            'executing':  'Searching the web…',
            'completed':  'Search complete',
            'error':      'Search failed'
        },
        'document_lookup': {
            'calling':    'Searching documents…',
            'executing':  'Searching documents…',
            'completed':  'Document search complete',
            'error':      'Document search failed'
        },
        'pkb_nl_command': {
            'calling':          'Processing PKB command…',
            'executing':        'Executing PKB operations…',
            'waiting_for_user': 'Waiting for your review…',
            'completed':        'PKB command complete',
            'error':            'PKB command failed'
        },
        'pkb_propose_memory': {
            'calling':          'Preparing memory proposal…',
            'executing':        'Analyzing memory to propose…',
            'waiting_for_user': 'Waiting for your review of proposed memories…',
            'completed':        'Memory proposal reviewed',
            'error':            'Memory proposal failed'
        },
        'pkb_delete_claim': {
            'calling':          'Deleting PKB claim…',
            'executing':        'Deleting PKB claim…',
            'completed':        'Claim deleted',
            'error':            'Claim deletion failed'
        },
    };

    var STATUS_ICONS = {
        'ask_clarification': '💬',
        'web_search':        '🔍',
        'document_lookup':   '📄',
        '_default':          '🔧',
        'pkb_nl_command':     '🗣️',
        'pkb_propose_memory': '📝',
        'pkb_delete_claim':   '🗑️',
    };

    /* ──────────────────────────────────────────────
     * ToolCallManager — the exported singleton.
     * ────────────────────────────────────────────── */
    var ToolCallManager = {

        /** Active tool calls being tracked: { toolId: { toolName, toolInput, status } } */
        activeToolCalls: {},

        /** Currently displayed modal tool_id (only one modal at a time) */
        currentModalToolId: null,

        /** Conversation ID for the current stream (set by handleToolInputRequest) */
        _currentConversationId: null,

        /** Whether a submit is currently in flight */
        _submitting: false,

        /* ────────────────────────────────────────────
         * showToolCallStatus
         * Called by renderStreamingResponse when a tool_call event arrives.
         * This is informational — the LLM has decided to call a tool.
         * Shows a brief status indicator in the chat area.
         *
         * @param {string} toolId   - Unique tool call ID from the API
         * @param {string} toolName - Name of the tool being called
         * @param {string} status   - "calling" | "executing" | "waiting_for_user" | "completed"
         * ──────────────────────────────────────────── */
        showToolCallStatus: function (toolId, toolName, status) {
            var existing = this.activeToolCalls[toolId] || {};
            this.activeToolCalls[toolId] = {
                toolName: toolName || existing.toolName,
                status: status || existing.status
            };

            var existingEl = document.getElementById('tool-status-' + toolId);

            if (existingEl) {
                // Update existing indicator
                var $existing = $(existingEl);
                $existing.find('.status-text').text(this._getStatusMessage(toolName, status));

                // Toggle completed styling
                $existing.toggleClass('completed', status === 'completed');
                $existing.toggleClass('error', status === 'error');

                // Remove spinner on completion / error
                if (status === 'completed' || status === 'error') {
                    $existing.find('.spinner-border').remove();
                    // Auto-fade after 4 seconds
                    setTimeout(function () {
                        $existing.addClass('fade-out');
                        setTimeout(function () { $existing.remove(); }, 600);
                    }, 4000);
                }
            } else {
                // Create new indicator and append to the streaming chat card
                var $indicator = this._createStatusIndicator(toolId, toolName, status);
                this._appendToStreamArea($indicator);
            }
        },

        /* ────────────────────────────────────────────
         * handleToolInputRequest
         * Called by renderStreamingResponse when a tool_input_request event arrives.
         * This means an interactive tool needs user input.
         * Shows the #tool-call-modal with appropriate form.
         *
         * @param {string} conversationId - Current conversation ID
         * @param {string} toolId         - Unique tool call ID
         * @param {string} toolName       - Name of the tool
         * @param {Object} uiSchema       - Schema describing what input is needed
         *   For ask_clarification: { questions: [{question: str, options: [str]}] }
         * ──────────────────────────────────────────── */
        handleToolInputRequest: function (conversationId, toolId, toolName, uiSchema) {
            console.log('[ToolCallManager] handleToolInputRequest called', {conversationId: conversationId, toolId: toolId, toolName: toolName, uiSchema: uiSchema});
            this._currentConversationId = conversationId;
            this.currentModalToolId = toolId;

            // Track
            this.activeToolCalls[toolId] = {
                toolName: toolName,
                status: 'waiting_for_user'
            };

            // Update inline indicator if one exists
            this.showToolCallStatus(toolId, toolName, 'waiting_for_user');

            // Build modal content based on tool
            var $modalTitle = $('#tool-call-modal-title');
            var $modalBody  = $('#tool-call-modal-body');
            var $submitBtn  = $('#tool-call-submit-btn');

            // Clear previous content
            $modalBody.empty();
            $submitBtn.removeClass('loading').prop('disabled', false);

            if (toolName === 'ask_clarification') {
                $modalTitle.html('<i class="fa fa-comments"></i>&nbsp;Clarification Questions');
                var questions = (uiSchema && Array.isArray(uiSchema.questions)) ? uiSchema.questions : [];
                if (questions.length === 0) {
                    $modalBody.html('<p class="text-muted">No questions provided.</p>');
                    $submitBtn.prop('disabled', true);
                } else {
                    // Instruction text
                    $modalBody.append(
                        '<p class="text-muted mb-3" style="font-size: 0.9rem;">' +
                        'The assistant would like to clarify a few things. Please select your answers:' +
                        '</p>'
                    );
                    this._renderClarificationQuestions($modalBody, questions);
                }
            } else if (toolName === 'pkb_propose_memory') {
                $modalTitle.html('<i class="fa fa-brain"></i>&nbsp;Review Proposed Memories');
                var claims = (uiSchema && Array.isArray(uiSchema.claims)) ? uiSchema.claims : [];
                var msg = (uiSchema && uiSchema.message) ? uiSchema.message : '';
                if (claims.length === 0) {
                    $modalBody.html('<p class="text-muted">No memory proposals provided.</p>');
                    $submitBtn.prop('disabled', true);
                } else {
                    if (msg) {
                        $modalBody.append(
                            '<p class="text-muted mb-3" style="font-size: 0.9rem;">' +
                            _escapeHtml(msg) + '</p>'
                        );
                    } else {
                        $modalBody.append(
                            '<p class="text-muted mb-3" style="font-size: 0.9rem;">' +
                            'Please review the proposed memory entries. Edit or remove any that are incorrect:' +
                            '</p>'
                        );
                    }
                    this._renderMemoryProposalForm($modalBody, claims);
                }
            } else {
                // Generic fallback for future tools
                $modalTitle.html('<i class="fa fa-wrench"></i>&nbsp;Tool: ' + _escapeHtml(toolName));
                $modalBody.html(
                    '<p class="text-muted">This tool requires your input.</p>' +
                    '<pre style="max-height:300px;overflow:auto;font-size:0.85rem;">' +
                    _escapeHtml(JSON.stringify(uiSchema, null, 2)) +
                    '</pre>' +
                    '<div class="form-group mt-3">' +
                    '  <label for="tool-call-generic-input" class="font-weight-bold">Your response:</label>' +
                    '  <textarea id="tool-call-generic-input" class="form-control" rows="3" ' +
                    '    placeholder="Type your response here…"></textarea>' +
                    '</div>'
                );
            }

            // Show modal
            $('#tool-call-modal').modal({ backdrop: 'static', keyboard: true });
            $('#tool-call-modal').modal('show');
            console.log('[ToolCallManager] Modal shown. currentModalToolId=', this.currentModalToolId, '_currentConversationId=', this._currentConversationId, 'activeToolCalls=', JSON.stringify(this.activeToolCalls));

            // Push notification (works in Electron desktop, browser, mobile)
            if (typeof NotificationManager !== 'undefined') {
                var notifTitle = toolName === 'ask_clarification' ? 'Clarification Needed' : 'Input Required';
                var notifBody = toolName === 'ask_clarification'
                    ? ((uiSchema && uiSchema.questions && uiSchema.questions[0]) ? uiSchema.questions[0].question : 'The assistant has questions for you.')
                    : 'The assistant needs your input to continue.';
                NotificationManager.notify({
                    title: notifTitle,
                    body: notifBody,
                    type: toolName === 'ask_clarification' ? 'clarification' : 'tool_request',
                    action: { type: 'flash-tab', tab: 'chat' },
                    tag: 'tool-input-' + toolId
                });
            }
        },

        /* ────────────────────────────────────────────
         * showToolResult
         * Called by renderStreamingResponse when a tool_result event arrives.
         * Shows a brief inline indicator that the tool completed.
         *
         * @param {string} toolId        - Unique tool call ID
         * @param {string} resultSummary  - Brief summary of what the tool returned
         * @param {number} [durationSeconds] - How long the tool took to execute
         * ──────────────────────────────────────────── */
        showToolResult: function (toolId, resultSummary, durationSeconds) {
            var entry = this.activeToolCalls[toolId];
            var toolName = (entry && entry.toolName) ? entry.toolName : 'unknown';

            // Update or create status indicator as completed
            this.showToolCallStatus(toolId, toolName, 'completed');

            // If there's a result summary, briefly show it
            if (resultSummary) {
                var existingEl = document.getElementById('tool-status-' + toolId);
                if (existingEl) {
                    var displayText = resultSummary;
                    if (durationSeconds != null) {
                        displayText += ' (' + durationSeconds.toFixed(1) + 's)';
                    }
                    $(existingEl).find('.status-text').text(displayText);
                }
            }

            // Remove from active tracking
            delete this.activeToolCalls[toolId];
        },

        /* ────────────────────────────────────────────
         * submitToolResponse
         * Submit user's response for an interactive tool back to the server.
         * POSTs to /tool_response/{conversationId}/{toolId}
         *
         * @param {string} conversationId - Current conversation ID
         * @param {string} toolId         - Unique tool call ID
         * @param {Object} responseData   - The user's response data
         * @returns {Promise}
         * ──────────────────────────────────────────── */
        submitToolResponse: function (conversationId, toolId, responseData) {
            var self = this;
            self._submitting = true;
            console.log('[ToolCallManager] submitToolResponse called', {conversationId: conversationId, toolId: toolId, responseData: responseData});
            var url = '/tool_response/' + encodeURIComponent(conversationId) + '/' + encodeURIComponent(toolId);
            console.log('[ToolCallManager] submitToolResponse: POSTing to', url);

            var $submitBtn = $('#tool-call-submit-btn');
            $submitBtn.addClass('loading').prop('disabled', true);
            $submitBtn.html('<span class="spinner-border spinner-border-sm mr-1"></span>Submitting…');

            return fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ response: responseData })
            })
            .then(function (resp) {
                if (!resp.ok) {
                    throw new Error('HTTP ' + resp.status);
                }
                return resp.json();
            })
            .then(function (data) {
                // Success — close modal, update status
                self._submitting = false;
                $('#tool-call-modal').modal('hide');
                self.showToolCallStatus(toolId, self.activeToolCalls[toolId] ? self.activeToolCalls[toolId].toolName : 'unknown', 'completed');
                _showToastOrAlert('Response submitted', 'success');
                return data;
            })
            .catch(function (err) {
                self._submitting = false;
                console.error('ToolCallManager: submit error', err);

                // Show error in modal instead of closing
                $submitBtn.removeClass('loading').prop('disabled', false);
                $submitBtn.html('<i class="fa fa-paper-plane"></i>&nbsp;Submit');

                var $errorDiv = $('#tool-call-modal-body .tool-call-submit-error');
                if ($errorDiv.length === 0) {
                    $errorDiv = $('<div class="alert alert-danger mt-2 tool-call-submit-error" style="font-size:0.9rem;"></div>');
                    $('#tool-call-modal-body').append($errorDiv);
                }
                $errorDiv.html(
                    '<i class="fa fa-exclamation-triangle"></i>&nbsp;' +
                    'Failed to submit response. Please try again.'
                ).show();

                throw err;
            });
        },

        /* ────────────────────────────────────────────
         * _renderClarificationQuestions
         * Render MCQ clarification questions in the modal body.
         * Follows the same radio-button pattern as ClarificationsManager
         * but uses radio buttons (single-select per question).
         *
         * @param {jQuery} $modalBody - jQuery element for the modal body
         * @param {Array}  questions  - [{question: str, options: [str]}]
         * ──────────────────────────────────────────── */
        _renderClarificationQuestions: function ($modalBody, questions) {
            var $container = $('<div id="tool-call-questions-list"></div>');

            questions.forEach(function (q, qIdx) {
                var questionText = q.question || q.prompt || '';
                var options = Array.isArray(q.options) ? q.options : [];

                var optionsHtml = options.map(function (opt, oIdx) {
                    var inputId = 'tool-q-' + qIdx + '-' + oIdx;
                    var radioName = 'tool-q-' + qIdx;
                    return (
                        '<div class="form-check">' +
                        '  <input class="form-check-input" type="radio"' +
                        '         name="' + _escapeHtml(radioName) + '"' +
                        '         id="' + _escapeHtml(inputId) + '"' +
                        '         value="' + _escapeHtml(opt) + '"' +
                        '         data-qidx="' + qIdx + '"' +
                        '         data-oidx="' + oIdx + '">' +
                        '  <label class="form-check-label" for="' + _escapeHtml(inputId) + '">' +
                        '    ' + _escapeHtml(opt) +
                        '  </label>' +
                        '</div>'
                    );
                }).join('');

                var questionHtml =
                    '<div class="tool-call-question mb-3">' +
                    '  <label class="question-label font-weight-bold">' +
                    '    Q' + (qIdx + 1) + ': ' + _escapeHtml(questionText) +
                    '  </label>' +
                    '  <div class="ml-3">' +
                    '    ' + optionsHtml +
                    '  </div>' +
                    '</div>';

                $container.append(questionHtml);
            });

            $modalBody.append($container);
        },

        /* ────────────────────────────────────────────
         * _renderMemoryProposalForm
         * Render editable memory proposal cards in the modal body.
         * Each claim gets a card with editable text, type selector, date fields,
         * tags, entities, and a remove button.
         *
         * @param {jQuery} $modalBody - jQuery element for the modal body
         * @param {Array}  claims    - [{text, claim_type, valid_from, valid_to, tags, entities, context}]
         * ──────────────────────────────────────────── */
        _renderMemoryProposalForm: function ($modalBody, claims) {
            var $container = $('<div id="tool-call-memory-proposals"></div>');
            var claimTypes = ['fact', 'preference', 'event', 'task', 'reminder', 'goal', 'note'];

            claims.forEach(function (claim, idx) {
                var typeOptions = claimTypes.map(function (t) {
                    var sel = (t === (claim.claim_type || 'note')) ? ' selected' : '';
                    return '<option value="' + t + '"' + sel + '>' + t.charAt(0).toUpperCase() + t.slice(1) + '</option>';
                }).join('');

                var tagsVal = Array.isArray(claim.tags) ? claim.tags.join(', ') : (claim.tags || '');
                var entitiesVal = Array.isArray(claim.entities) ? claim.entities.join(', ') : (claim.entities || '');

                var cardHtml =
                    '<div class="card mb-3 memory-proposal-card" data-claim-idx="' + idx + '">' +
                    '  <div class="card-body p-3">' +
                    '    <div class="d-flex justify-content-between align-items-start mb-2">' +
                    '      <strong class="text-muted">Memory #' + (idx + 1) + '</strong>' +
                    '      <button type="button" class="btn btn-sm btn-outline-danger memory-proposal-remove" data-idx="' + idx + '" title="Remove">' +
                    '        <i class="fa fa-times"></i>' +
                    '      </button>' +
                    '    </div>' +
                    '    <div class="form-group mb-2">' +
                    '      <textarea class="form-control memory-prop-text" rows="2" data-idx="' + idx + '"' +
                    '        placeholder="Memory text">' + _escapeHtml(claim.text || '') + '</textarea>' +
                    '    </div>' +
                    '    <div class="form-row mb-2">' +
                    '      <div class="col-md-4">' +
                    '        <label class="small text-muted">Type</label>' +
                    '        <select class="form-control form-control-sm memory-prop-type" data-idx="' + idx + '">' +
                    '          ' + typeOptions +
                    '        </select>' +
                    '      </div>' +
                    '      <div class="col-md-4">' +
                    '        <label class="small text-muted">From</label>' +
                    '        <input type="date" class="form-control form-control-sm memory-prop-from" data-idx="' + idx + '"' +
                    '          value="' + _escapeHtml(claim.valid_from || '') + '">' +
                    '      </div>' +
                    '      <div class="col-md-4">' +
                    '        <label class="small text-muted">Due / To</label>' +
                    '        <input type="date" class="form-control form-control-sm memory-prop-to" data-idx="' + idx + '"' +
                    '          value="' + _escapeHtml(claim.valid_to || '') + '">' +
                    '      </div>' +
                    '    </div>' +
                    '    <div class="form-row mb-2">' +
                    '      <div class="col-md-6">' +
                    '        <label class="small text-muted">Tags (comma-separated)</label>' +
                    '        <input type="text" class="form-control form-control-sm memory-prop-tags" data-idx="' + idx + '"' +
                    '          value="' + _escapeHtml(tagsVal) + '" placeholder="e.g. work, personal">' +
                    '      </div>' +
                    '      <div class="col-md-6">' +
                    '        <label class="small text-muted">Entities (comma-separated)</label>' +
                    '        <input type="text" class="form-control form-control-sm memory-prop-entities" data-idx="' + idx + '"' +
                    '          value="' + _escapeHtml(entitiesVal) + '" placeholder="e.g. John, Acme Corp">' +
                    '      </div>' +
                    '    </div>' +
                    '    <div class="form-group mb-0">' +
                    '      <label class="small text-muted">Context</label>' +
                    '        <input type="text" class="form-control form-control-sm memory-prop-context" data-idx="' + idx + '"' +
                    '          value="' + _escapeHtml(claim.context || '') + '" placeholder="Source or context">' +
                    '    </div>' +
                    '  </div>' +
                    '</div>';

                $container.append(cardHtml);
            });

            // Remove button handler
            $container.on('click', '.memory-proposal-remove', function () {
                $(this).closest('.memory-proposal-card').slideUp(200, function () {
                    $(this).remove();
                });
            });

            $modalBody.append($container);
        },

        /* ────────────────────────────────────────────
         * _collectClarificationAnswers
         * Collect answers from the tool-call clarification form.
         *
         * @returns {Object} - { answers: [{question: str, selected_option: str}] }
         * ──────────────────────────────────────────── */
        _collectClarificationAnswers: function () {
            var answers = [];
            var $container = $('#tool-call-questions-list');
            var self = this;

            $container.find('.tool-call-question').each(function (qIdx) {
                var $q = $(this);
                var questionText = $q.find('.question-label').text().replace(/^Q\d+:\s*/, '').trim();
                var $selected = $q.find('input[type="radio"]:checked');

                if ($selected.length > 0) {
                    answers.push({
                        question: questionText,
                        selected_option: $selected.val()
                    });
                }
            });

            return { answers: answers };
        },


        /* ────────────────────────────────────────────
         * _collectMemoryProposalResponse
         * Collect edited memory proposals from the modal form.
         *
         * @returns {Object} - { claims: [{text, claim_type, valid_from, valid_to, tags, entities, context}] }
         * ──────────────────────────────────────────── */
        _collectMemoryProposalResponse: function () {
            var claims = [];
            $('#tool-call-memory-proposals .memory-proposal-card:visible').each(function () {
                var $card = $(this);
                var text = $card.find('.memory-prop-text').val() || '';
                if (!text.trim()) return;  // Skip empty entries
                var tagsStr = $card.find('.memory-prop-tags').val() || '';
                var entitiesStr = $card.find('.memory-prop-entities').val() || '';
                claims.push({
                    text: text.trim(),
                    claim_type: $card.find('.memory-prop-type').val() || 'note',
                    valid_from: $card.find('.memory-prop-from').val() || null,
                    valid_to: $card.find('.memory-prop-to').val() || null,
                    tags: tagsStr ? tagsStr.split(',').map(function(s) { return s.trim(); }).filter(Boolean) : [],
                    entities: entitiesStr ? entitiesStr.split(',').map(function(s) { return s.trim(); }).filter(Boolean) : [],
                    context: ($card.find('.memory-prop-context').val() || '').trim() || null
                });
            });
            return { claims: claims };
        },
        /* ────────────────────────────────────────────
         * _collectGenericResponse
         * Collect a free-text response from the generic tool input.
         *
         * @returns {Object} - { text: str }
         * ──────────────────────────────────────────── */
        _collectGenericResponse: function () {
            var text = ($('#tool-call-generic-input').val() || '').trim();
            return { text: text };
        },

        /* ────────────────────────────────────────────
         * _getStatusMessage
         * Get a human-readable status message for a tool.
         *
         * @param {string} toolName
         * @param {string} status
         * @returns {string}
         * ──────────────────────────────────────────── */
        _getStatusMessage: function (toolName, status) {
            var toolMessages = STATUS_MESSAGES[toolName];
            if (toolMessages && toolMessages[status]) {
                return toolMessages[status];
            }
            // Fallback: Title-case the tool name and humanize the status
            var displayName = String(toolName || 'Tool').replace(/_/g, ' ');
            return displayName + ': ' + String(status || 'working');
        },

        /* ────────────────────────────────────────────
         * _createStatusIndicator
         * Create a status indicator element for a tool call.
         * Returns a jQuery element.
         *
         * @param {string} toolId
         * @param {string} toolName
         * @param {string} status
         * @returns {jQuery}
         * ──────────────────────────────────────────── */
        _createStatusIndicator: function (toolId, toolName, status) {
            var icon = STATUS_ICONS[toolName] || STATUS_ICONS['_default'];
            var message = this._getStatusMessage(toolName, status);
            var isTerminal = (status === 'completed' || status === 'error');
            var statusClass = isTerminal ? (' ' + status) : '';

            var html =
                '<div class="tool-call-status' + statusClass + '" id="tool-status-' + _escapeHtml(toolId) + '">' +
                '  <span class="status-icon">' + icon + '</span>';

            // Show spinner for non-terminal states
            if (!isTerminal) {
                html += '  <span class="spinner-border spinner-border-sm text-muted" role="status"></span>';
            }

            html +=
                '  <span class="status-text">' + _escapeHtml(message) + '</span>' +
                '</div>';

            return $(html);
        },

        /* ────────────────────────────────────────────
         * _appendToStreamArea
         * Append a jQuery element to the currently-streaming chat card's
         * content area. Falls back to the last .actual-card-text if no
         * card is specifically marked as streaming.
         *
         * @param {jQuery} $el - Element to append
         * ──────────────────────────────────────────── */
        _appendToStreamArea: function ($el) {
            // Try to find the actively-streaming card first
            var $streamCard = $('[data-live-stream="true"]');
            if ($streamCard.length > 0) {
                var $statusDiv = $streamCard.find('.status-div');
                if ($statusDiv.length > 0) {
                    $el.insertBefore($statusDiv);
                    return;
                }
                var $cardText = $streamCard.find('.actual-card-text').last();
                if ($cardText.length > 0) {
                    $cardText.append($el);
                    return;
                }
            }

            // Fallback: append to the last message card's text area
            var $lastCardText = $('#chatView .actual-card-text').last();
            if ($lastCardText.length > 0) {
                $lastCardText.append($el);
            }
        },

        /* ────────────────────────────────────────────
         * _handleSubmit
         * Internal handler for the Submit button click.
         * Collects the response data based on the active tool and submits.
         * ──────────────────────────────────────────── */
        _handleSubmit: function () {
            console.log('[ToolCallManager] _handleSubmit called. _submitting=', this._submitting, 'currentModalToolId=', this.currentModalToolId, '_currentConversationId=', this._currentConversationId);
            if (this._submitting) { console.log('[ToolCallManager] _handleSubmit: blocked by _submitting=true'); return; }

            var toolId = this.currentModalToolId;
            var conversationId = this._currentConversationId;

            if (!toolId || !conversationId) {
                console.log('[ToolCallManager] _handleSubmit: early return — toolId=', toolId, 'conversationId=', conversationId);
                _showToastOrAlert('No active tool call to respond to.', 'warning');
                return;
            }

            var entry = this.activeToolCalls[toolId];
            var toolName = (entry && entry.toolName) ? entry.toolName : 'unknown';
            console.log('[ToolCallManager] _handleSubmit: toolName=', toolName, 'entry=', JSON.stringify(entry));
            var responseData;

            if (toolName === 'ask_clarification') {
                responseData = this._collectClarificationAnswers();
                console.log('[ToolCallManager] _handleSubmit: collected answers=', JSON.stringify(responseData));
                // Validate at least one answer
                if (!responseData.answers || responseData.answers.length === 0) {
                    _showToastOrAlert('Please select at least one option.', 'warning');
                    return;
                }
            } else if (toolName === 'pkb_propose_memory') {
                responseData = this._collectMemoryProposalResponse();
                console.log('[ToolCallManager] _handleSubmit: collected memory proposals=', JSON.stringify(responseData));
                // Validate at least one claim
                if (!responseData.claims || responseData.claims.length === 0) {
                    _showToastOrAlert('Please keep at least one memory entry (or use Skip to cancel).', 'warning');
                    return;
                }
            } else {
                responseData = this._collectGenericResponse();
                if (!responseData.text) {
                    _showToastOrAlert('Please enter a response.', 'warning');
                    return;
                }
            }

            console.log('[ToolCallManager] _handleSubmit: calling submitToolResponse with', {conversationId: conversationId, toolId: toolId, responseData: responseData});
            this.submitToolResponse(conversationId, toolId, responseData);
        },

        /* ────────────────────────────────────────────
         * _handleSkip
         * Internal handler for the Skip/Cancel button.
         * Submits a "skipped" response so the backend knows user declined.
         * ──────────────────────────────────────────── */
        _handleSkip: function () {
            var toolId = this.currentModalToolId;
            var conversationId = this._currentConversationId;

            if (toolId && conversationId) {
                // Notify server that user skipped
                this.submitToolResponse(conversationId, toolId, { skipped: true });
            } else {
                // Just close the modal
                $('#tool-call-modal').modal('hide');
            }
        },

        /* ────────────────────────────────────────────
         * reset
         * Reset state. Called when a new message send begins.
         * ──────────────────────────────────────────── */
        reset: function () {
            this.activeToolCalls = {};
            this.currentModalToolId = null;
            this._currentConversationId = null;
            this._submitting = false;

            // Close any open modal
            try {
                $('#tool-call-modal').modal('hide');
            } catch (e) { /* ignore if modal not in DOM yet */ }

            // Remove any lingering status indicators
            $('.tool-call-status').remove();
        },

        /* ────────────────────────────────────────────
         * setupEventHandlers
         * Initialize event handlers. Call once on page load.
         * ──────────────────────────────────────────── */
        setupEventHandlers: function () {
            var self = this;

            // Inject CSS styles
            _injectStyles();

            // Modal submit button
            $(document).off('click.toolcall-submit').on('click.toolcall-submit', '#tool-call-submit-btn', function (e) {
                console.log('[ToolCallManager] Submit button clicked (delegated handler)');
                e.preventDefault();
                self._handleSubmit();
            });
            console.log('[ToolCallManager] setupEventHandlers: delegated click handler bound');

            // Modal skip/cancel button — use data-dismiss to let Bootstrap close,
            // but also notify the server.
            $(document).off('click.toolcall-skip').on('click.toolcall-skip', '#tool-call-modal .btn-secondary[data-dismiss="modal"]', function () {
                // The modal will close via Bootstrap's data-dismiss.
                // If we have an active tool call, notify the server it was skipped.
                if (self.currentModalToolId && self._currentConversationId && !self._submitting) {
                    var toolId = self.currentModalToolId;
                    var convId = self._currentConversationId;
                    // Fire-and-forget skip notification
                    fetch('/tool_response/' + encodeURIComponent(convId) + '/' + encodeURIComponent(toolId), {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ response: { skipped: true } })
                    }).catch(function () { /* ignore */ });
                }
            });

            // Clean up state when modal is hidden (by any means)
            $(document).off('hidden.bs.modal.toolcall').on('hidden.bs.modal.toolcall', '#tool-call-modal', function () {
                self.currentModalToolId = null;
                self._submitting = false;
                // Reset submit button
                var $submitBtn = $('#tool-call-submit-btn');
                $submitBtn.removeClass('loading').prop('disabled', false);
                $submitBtn.html('<i class="fa fa-paper-plane"></i>&nbsp;Submit');
                // Clear error messages
                $('#tool-call-modal-body .tool-call-submit-error').remove();
            });

            // Keyboard: Enter to submit when modal is open
            $(document).off('keydown.toolcall-keyboard').on('keydown.toolcall-keyboard', function (e) {
                if (!$('#tool-call-modal').hasClass('show')) return;
                if (e.key === 'Enter' && !e.shiftKey && !e.ctrlKey && !e.metaKey) {
                    // Only submit if we're not focused on a textarea
                    var activeTag = (document.activeElement && document.activeElement.tagName) || '';
                    if (activeTag.toLowerCase() === 'textarea') return;
                    e.preventDefault();
                    self._handleSubmit();
                }
            });
        }
    };

    /* ──────────────────────────────────────────────
     * Export to global scope
     * ────────────────────────────────────────────── */
    window.ToolCallManager = ToolCallManager;

    /* ──────────────────────────────────────────────
     * Auto-initialize on DOM ready
     * ────────────────────────────────────────────── */
    $(document).ready(function () {
        ToolCallManager.setupEventHandlers();
    });

})();
