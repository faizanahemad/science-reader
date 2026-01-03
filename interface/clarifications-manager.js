/**
 * ClarificationsManager
 * ---------------------
 * UI-only manager for the manual "Clarify" flow:
 * - Calls `POST /clarify_intent/<conversation_id>` with the current draft message.
 * - Renders up to 3 MCQ questions in a Bootstrap modal.
 * - Appends selected answers into `#messageText` using a stable block.
 * - Supports "Apply" and "Apply & Send".
 *
 * Design principles:
 * - Fail-open: any error should let the user continue without clarifications.
 * - Avoid UI/server mismatch: we only modify `#messageText`, and the existing send path
 *   reads from `#messageText` (then clears it) when sending.
 */
(function () {
    'use strict';

    const BLOCK_START = '\n\n[Clarifications]\n';

    function _escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = (text == null) ? '' : String(text);
        return div.innerHTML;
    }

    function _stripExistingClarificationsBlock(text) {
        if (typeof text !== 'string') return '';
        const idx = text.lastIndexOf(BLOCK_START);
        if (idx === -1) return text;
        return text.slice(0, idx).trimEnd();
    }

    function _showToastOrAlert(message, level) {
        if (typeof showToast === 'function') {
            showToast(message, level || 'info');
            return;
        }
        alert(message);
    }

    const ClarificationsManager = {
        currentConversationId: null,
        currentDraftText: null,
        currentQuestions: [],
        lastRequestController: null,
        autoSendAfterApply: false,

        /**
         * Entry point: request questions then show the modal.
         *
         * @param {string} conversationId
         * @param {string} messageText
         * @param {{autoSend?: boolean}=} opts
         */
        requestAndShowClarifications: function (conversationId, messageText, opts) {
            this.currentConversationId = conversationId;
            this.currentDraftText = messageText;
            this.currentQuestions = [];
            this.autoSendAfterApply = !!(opts && opts.autoSend);

            this._setModalState('loading');
            $('#clarifications-modal').modal('show');

            this._fetchClarifications(conversationId, messageText)
                .then((data) => this._handleClarificationsResponse(data))
                .catch((err) => this._handleError(err));
        },

        _fetchClarifications: function (conversationId, messageText) {
            // Abort any in-flight request to keep UI responsive.
            try {
                if (this.lastRequestController) {
                    this.lastRequestController.abort();
                }
            } catch (e) {}

            const controller = new AbortController();
            this.lastRequestController = controller;

            const timeoutMs = 10000;
            const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

            const checkboxes = (typeof getOptions === 'function') ? getOptions('chat-options', 'assistant') : {};
            const links = $('#linkInput').length ? $('#linkInput').val().split('\n') : [];
            const search = $('#searchInput').length ? $('#searchInput').val().split('\n') : [];

            return fetch(`/clarify_intent/${conversationId}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                signal: controller.signal,
                body: JSON.stringify({
                    messageText: messageText,
                    checkboxes: checkboxes,
                    links: links,
                    search: search
                })
            })
                .then((resp) => {
                    clearTimeout(timeoutId);
                    if (!resp.ok) {
                        throw new Error(`HTTP ${resp.status}`);
                    }
                    return resp.json();
                });
        },

        _handleClarificationsResponse: function (data) {
            const questions = (data && Array.isArray(data.questions)) ? data.questions : [];
            const needs = Boolean(data && data.needs_clarification);

            if (!needs || questions.length === 0) {
                this._setModalState('not-needed');
                // Small auto-close so user isn't stuck in a modal for "no-op" results.
                setTimeout(() => {
                    $('#clarifications-modal').modal('hide');
                    if (this.autoSendAfterApply && typeof sendMessageCallback === 'function') {
                        // Skip auto-clarify re-entry to avoid loops.
                        sendMessageCallback(true);
                    }
                }, 900);
                return;
            }

            this.currentQuestions = questions.slice(0, 3);
            this._renderQuestions(this.currentQuestions);
            this._setModalState('questions');
        },

        _renderQuestions: function (questions) {
            const container = $('#clarifications-questions-list');
            container.empty();

            questions.forEach((q, qIdx) => {
                const qId = q.id || `q${qIdx + 1}`;
                const prompt = q.prompt || '';
                const options = Array.isArray(q.options) ? q.options : [];

                const optionsHtml = options.map((opt, oIdx) => {
                    const optId = opt.id || `${qId}_opt${oIdx + 1}`;
                    const label = opt.label || '';
                    const inputId = `clarification-${qId}-${optId}`;
                    const labelLower = String(label || '').toLowerCase();
                    const isOther = labelLower.includes('other') && (labelLower.includes('specify') || labelLower.includes('please'));
                    return `
                        <div class="form-check">
                            <input class="form-check-input clarification-option" type="checkbox"
                                   name="clarification-q-${_escapeHtml(qId)}"
                                   id="${_escapeHtml(inputId)}"
                                   value="${_escapeHtml(optId)}"
                                   data-qid="${_escapeHtml(qId)}"
                                   data-optid="${_escapeHtml(optId)}"
                                   data-isother="${isOther ? '1' : '0'}">
                            <label class="form-check-label" for="${_escapeHtml(inputId)}" style="font-size: 0.95rem;">
                                ${_escapeHtml(label)}
                            </label>
                            <div class="mt-1" style="display: ${isOther ? 'block' : 'none'};">
                                <input
                                    type="text"
                                    class="form-control form-control-sm clarification-other-input"
                                    id="${_escapeHtml(inputId)}-othertext"
                                    placeholder="Please specify..."
                                    style="max-width: 520px; display: ${isOther ? 'none' : 'none'};"
                                />
                            </div>
                        </div>
                    `;
                }).join('');

                const questionHtml = `
                    <div class="mb-4">
                        <div style="font-size: 0.98rem; font-weight: 600; margin-bottom: 0.35rem;">
                            Q${qIdx + 1}: ${_escapeHtml(prompt)}
                        </div>
                        <div class="ml-3">
                            ${optionsHtml}
                        </div>
                    </div>
                `;
                container.append(questionHtml);
            });

            // Toggle "Other (please specify)" inputs.
            container.find('.clarification-option').off('change.clarifications').on('change.clarifications', function () {
                try {
                    const $opt = $(this);
                    const isOther = $opt.attr('data-isother') === '1';
                    if (!isOther) return;
                    const qid = $opt.attr('data-qid');
                    const optid = $opt.attr('data-optid');
                    const inputId = `#clarification-${qid}-${optid}-othertext`;
                    const $otherInput = $(inputId);
                    if (!$otherInput.length) return;
                    if ($opt.is(':checked')) {
                        $otherInput.show().focus();
                    } else {
                        $otherInput.hide().val('');
                    }
                } catch (e) {}
            });
        },

        _collectAnswers: function () {
            const answers = [];
            this.currentQuestions.forEach((q, qIdx) => {
                const qId = q.id || `q${qIdx + 1}`;
                const prompt = q.prompt || '';
                const selected = $(`input[name="clarification-q-${qId}"]:checked`).map(function () { return $(this).val(); }).get();
                if (!selected || selected.length === 0) return;
                const selectedLabels = [];
                selected.forEach((sel) => {
                    const opt = (Array.isArray(q.options) ? q.options : []).find(o => (o && o.id) === sel);
                    const label = opt ? (opt.label || sel) : sel;
                    const labelLower = String(label || '').toLowerCase();
                    const isOther = labelLower.includes('other') && (labelLower.includes('specify') || labelLower.includes('please'));
                    if (isOther) {
                        const inputId = `#clarification-${qId}-${sel}-othertext`;
                        const otherVal = ($(inputId).val() || '').trim();
                        if (otherVal.length > 0) {
                            selectedLabels.push(`Other: ${otherVal}`);
                        } else {
                            selectedLabels.push(String(label));
                        }
                    } else {
                        selectedLabels.push(String(label));
                    }
                });
                answers.push({ prompt: prompt, answer: selectedLabels.join('; ') });
            });
            return answers;
        },

        _buildAppendBlock: function (answers) {
            if (!Array.isArray(answers) || answers.length === 0) return '';
            let text = BLOCK_START;
            answers.forEach((qa, idx) => {
                text += `- Q${idx + 1}: ${qa.prompt}\n`;
                text += `  A: ${qa.answer}\n`;
            });
            return text;
        },

        applyToComposer: function () {
            const currentText = $('#messageText').val() || '';
            const stripped = _stripExistingClarificationsBlock(currentText);
            const answers = this._collectAnswers();
            const append = this._buildAppendBlock(answers);

            if (!append) {
                _showToastOrAlert('Please select at least one option.', 'warning');
                return false;
            }

            $('#messageText').val(stripped + append);
            $('#messageText').trigger('input');
            $('#clarifications-modal').modal('hide');
            return true;
        },

        applyAndSend: function () {
            const applied = this.applyToComposer();
            if (!applied) {
                return;
            }
            setTimeout(() => {
                if (typeof sendMessageCallback === 'function') {
                    // Skip auto-clarify re-entry to avoid loops.
                    sendMessageCallback(true);
                }
            }, 250);
        },

        _handleError: function (err) {
            console.error('Clarifications error:', err);
            $('#clarifications-error-text').text('Failed to get clarifications. You can proceed without them.');
            this._setModalState('error');
            setTimeout(() => $('#clarifications-modal').modal('hide'), 1600);
        },

        _setModalState: function (state) {
            $('#clarifications-loading').hide();
            $('#clarifications-questions').hide();
            $('#clarifications-not-needed').hide();
            $('#clarifications-error').hide();
            $('#clarifications-apply-btn').hide();
            $('#clarifications-apply-send-btn').hide();

            if (state === 'loading') {
                $('#clarifications-loading').show();
            } else if (state === 'questions') {
                $('#clarifications-questions').show();
                $('#clarifications-apply-btn').show();
                $('#clarifications-apply-send-btn').show();
            } else if (state === 'not-needed') {
                $('#clarifications-not-needed').show();
            } else if (state === 'error') {
                $('#clarifications-error').show();
            }
        },

        setupEventHandlers: function () {
            $('#clarifications-apply-btn').on('click', () => this.applyToComposer());
            $('#clarifications-apply-send-btn').on('click', () => this.applyAndSend());
        }
    };

    window.ClarificationsManager = ClarificationsManager;

    $(document).ready(function () {
        if ($('#clarifications-modal').length) {
            ClarificationsManager.setupEventHandlers();
        }
    });
})();


