/**
 * compare-manager.js — Response Diffing
 *
 * Re-run any assistant response with different model/params and view
 * a side-by-side comparison with LLM-generated semantic diff
 * (same approach as the multi-model tab diff feature).
 */

var CompareManager = (function () {
    'use strict';

    let _streamController = null;

    // ─── Semantic diff rendering (mirrors multi-tab diff in common.js) ────

    function renderSemanticDiff(diffData, newModel) {
        var stats = diffData.stats || {};
        var sections = diffData.diff_sections || [];
        var $container = $('<div class="diff-tab-content"></div>');

        if (!sections.length) {
            $container.append('<div class="diff-all-agree">✅ Both responses are essentially the same</div>');
            return $container;
        }

        var badge = diffData.badge_summary || '';
        var shortName = newModel.replace(/^.*\//, '');
        var $group = $('<div class="diff-model-group"></div>');
        $group.append('<h6 class="diff-model-header">vs ' + shortName + (badge ? ' <span class="model-diff-badge">' + badge + '</span>' : '') + '</h6>');

        for (var i = 0; i < sections.length; i++) {
            var sec = sections[i];
            var icon = sec.type === 'addition' ? '✅' : sec.type === 'contradiction' ? '⚠️' : '❌';
            var typeClass = 'diff-' + sec.type;
            var $sec = $('<div class="diff-section ' + typeClass + '"></div>');
            $sec.append('<div class="diff-section-header">' + icon + ' ' + (sec.topic || '') + '</div>');
            var detailHtml = (typeof marked !== 'undefined' && marked.parse) ? marked.parse(sec.detail || '') : (sec.detail || '');
            $sec.append('<div class="diff-section-body">' + detailHtml + '</div>');
            $group.append($sec);
        }

        $container.append($group);
        return $container;
    }

    // ─── Modal HTML ───────────────────────────────────────────────────────

    function ensureModal() {
        if ($('#compare-modal').length) return;

        const html = `
        <div id="compare-modal" class="modal fade" tabindex="-1" aria-hidden="true" style="z-index:1086;">
            <div class="modal-dialog modal-xl modal-dialog-scrollable" style="max-width:95vw;">
                <div class="modal-content" style="height:85vh;">
                    <div class="modal-header py-2">
                        <h6 class="modal-title mb-0"><i class="bi bi-arrow-left-right mr-1"></i>Response Comparison</h6>
                        <button type="button" class="close" data-dismiss="modal">&times;</button>
                    </div>
                    <div class="modal-body p-0 d-flex flex-column" style="overflow:hidden;">
                        <!-- Controls bar -->
                        <div class="px-3 py-2 border-bottom bg-light" id="compare-controls">
                            <div class="d-flex flex-wrap align-items-center gap-2" style="gap:0.5rem;">
                                <select id="compare-model-select" class="form-control form-control-sm" style="width:auto;max-width:250px;"></select>
                                <label class="mb-0 small text-muted">Temp:</label>
                                <input type="range" id="compare-temp-slider" min="0" max="2" step="0.1" value="0.7" style="width:100px;">
                                <span id="compare-temp-value" class="small text-muted">0.7</span>
                                <input type="text" id="compare-system-override" class="form-control form-control-sm" placeholder="Steering instruction (optional)" style="width:220px;">
                                <button id="compare-generate-btn" class="btn btn-sm btn-primary"><i class="bi bi-play-fill mr-1"></i>Generate</button>
                                <button id="compare-stop-btn" class="btn btn-sm btn-danger d-none"><i class="bi bi-stop-fill mr-1"></i>Stop</button>
                            </div>
                        </div>
                        <!-- View toggle -->
                        <div class="px-3 py-1 border-bottom d-flex align-items-center" style="gap:0.5rem;">
                            <div class="btn-group btn-group-sm" role="group">
                                <button class="btn btn-outline-secondary compare-view-toggle active" data-view="side-by-side">Side by Side</button>
                                <button class="btn btn-outline-secondary compare-view-toggle" data-view="diff">⚡ Diff</button>
                            </div>
                            <span id="compare-status" class="small text-muted ml-2"></span>
                        </div>
                        <!-- Content area -->
                        <div id="compare-content" class="flex-grow-1 d-flex" style="overflow:hidden;">
                            <!-- Side by side view -->
                            <div id="compare-side-by-side" class="w-100" style="display:flex;overflow:hidden;">
                                <div class="w-50 border-right d-flex flex-column" style="overflow:hidden;">
                                    <div class="px-2 py-1 bg-light border-bottom small font-weight-bold">Original <span id="compare-original-model" class="text-muted font-weight-normal"></span></div>
                                    <div id="compare-left-pane" class="flex-grow-1 p-3" style="overflow-y:auto;font-size:0.9rem;"></div>
                                </div>
                                <div class="w-50 d-flex flex-column" style="overflow:hidden;">
                                    <div class="px-2 py-1 bg-light border-bottom small font-weight-bold">New <span id="compare-new-model" class="text-muted font-weight-normal"></span></div>
                                    <div id="compare-right-pane" class="flex-grow-1 p-3" style="overflow-y:auto;font-size:0.9rem;"></div>
                                </div>
                            </div>
                            <!-- Diff view (hidden by default) -->
                            <div id="compare-diff-view" class="w-100 p-3" style="overflow-y:auto;font-size:0.9rem;display:none;"></div>
                        </div>
                    </div>
                </div>
            </div>
        </div>`;
        $('body').append(html);
        bindModalEvents();
    }

    function bindModalEvents() {
        $('#compare-temp-slider').on('input', function () {
            $('#compare-temp-value').text($(this).val());
        });

        // View toggle — use document-level delegation to guarantee it fires
        $(document).on('click', '.compare-view-toggle', function (e) {
            e.preventDefault();
            e.stopPropagation();
            $('.compare-view-toggle').removeClass('active');
            $(this).addClass('active');
            var view = $(this).attr('data-view');
            if (view === 'side-by-side') {
                $('#compare-side-by-side')[0].style.display = 'flex';
                $('#compare-diff-view')[0].style.display = 'none';
            } else {
                $('#compare-side-by-side')[0].style.display = 'none';
                $('#compare-diff-view')[0].style.display = 'block';
            }
        });

        $('#compare-modal').on('click', '#compare-generate-btn', function () {
            startComparison();
        });

        $('#compare-modal').on('click', '#compare-stop-btn', function () {
            if (_streamController) {
                _streamController.cancel();
                _streamController = null;
            }
            resetButtons();
            $('#compare-status').text('Stopped');
        });

        $('#compare-modal').on('hidden.bs.modal', function () {
            if (_streamController) {
                _streamController.cancel();
                _streamController = null;
            }
        });
    }

    // ─── State ────────────────────────────────────────────────────────────

    let _currentContext = null; // { conversationId, messageId, originalText }

    // ─── Public API ───────────────────────────────────────────────────────

    function open(conversationId, messageId, originalText) {
        ensureModal();
        _currentContext = { conversationId, messageId, originalText };

        const $select = $('#compare-model-select').empty();
        const models = (window.ModelCatalog && window.ModelCatalog.getAll()) || [];
        if (models.length) {
            models.forEach(m => $select.append($('<option>').val(m).text(m)));
        } else {
            ['anthropic/claude-opus-latest', 'google/gemini-pro-latest', 'openai/gpt-5.5',
             'anthropic/claude-sonnet-4.6', 'deepseek/deepseek-v4-pro', 'google/gemini-flash-latest']
                .forEach(m => $select.append($('<option>').val(m).text(m)));
        }

        $('#compare-left-pane').html(marked.parse(originalText.replace(/\n/g, '  \n')));
        $('#compare-right-pane').html('<span class="text-muted">Click "Generate" to run with selected model</span>');
        $('#compare-diff-view').html('');
        $('#compare-status').text('');
        $('#compare-original-model').text('');
        $('#compare-new-model').text('');
        $('#compare-stop-btn').addClass('d-none');
        $('#compare-generate-btn').removeClass('d-none');

        // Reset to side-by-side view
        $('#compare-side-by-side')[0].style.display = 'flex';
        $('#compare-diff-view')[0].style.display = 'none';
        $('.compare-view-toggle').removeClass('active');
        $('.compare-view-toggle[data-view="side-by-side"]').addClass('active');

        $('#compare-modal').modal('show');
    }

    function startComparison() {
        if (!_currentContext) return;

        const model = $('#compare-model-select').val();
        const temperature = parseFloat($('#compare-temp-slider').val());
        const systemOverride = $('#compare-system-override').val().trim();

        $('#compare-right-pane').html('');
        $('#compare-diff-view').html('<div class="diff-loading-spinner"><span class="spinner-border spinner-border-sm"></span> Waiting for response...</div>');
        $('#compare-status').text('Streaming...');
        $('#compare-new-model').text(model);
        $('#compare-generate-btn').addClass('d-none');
        $('#compare-stop-btn').removeClass('d-none');

        const { conversationId, messageId, originalText } = _currentContext;
        const abortController = new AbortController();

        fetch(`/rerun_message/${conversationId}/${messageId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                model, temperature, system_prompt_override: systemOverride,
                preamble_options: (window.chatSettingsState && window.chatSettingsState.preamble_options) || []
            }),
            signal: abortController.signal
        })
        .then(response => {
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';
            let accumulated = '';

            _streamController = { cancel: () => { abortController.abort(); reader.cancel(); } };

            function processLine(line) {
                if (!line) return false;
                try {
                    const part = JSON.parse(line);
                    if (part.error) {
                        $('#compare-right-pane').append($('<div class="text-danger">').text(part.text));
                        resetButtons();
                        return true;
                    }
                    if (part.text) {
                        accumulated += part.text;
                        $('#compare-right-pane').html(marked.parse(accumulated.replace(/\n/g, '  \n')));
                    }
                    if (part.completed) {
                        onStreamComplete(originalText, accumulated, model);
                        return true;
                    }
                } catch (e) { /* skip malformed line */ }
                return false;
            }

            function read() {
                reader.read().then(({ value, done }) => {
                    if (done) {
                        if (buffer.trim()) processLine(buffer.trim());
                        if (accumulated) onStreamComplete(originalText, accumulated, model);
                        else resetButtons();
                        return;
                    }
                    buffer += decoder.decode(value, { stream: true });
                    let boundary = buffer.indexOf('\n');
                    while (boundary !== -1) {
                        const line = buffer.slice(0, boundary).trim();
                        buffer = buffer.slice(boundary + 1);
                        if (processLine(line)) return;
                        boundary = buffer.indexOf('\n');
                    }
                    setTimeout(read, 10);
                }).catch(err => {
                    if (err.name !== 'AbortError') {
                        $('#compare-status').text('Error: ' + err.message);
                    }
                    resetButtons();
                });
            }
            read();
        })
        .catch(err => {
            if (err.name !== 'AbortError') {
                $('#compare-status').text('Error: ' + err.message);
            }
            resetButtons();
        });
    }

    function resetButtons() {
        _streamController = null;
        $('#compare-stop-btn').addClass('d-none');
        $('#compare-generate-btn').removeClass('d-none');
    }

    function onStreamComplete(originalText, newText, model) {
        resetButtons();
        $('#compare-status').text('Generating semantic diff...');
        $('#compare-diff-view').html('<div class="diff-loading-spinner"><span class="spinner-border spinner-border-sm"></span> Generating comparison...</div>');

        // Call the semantic diff endpoint (same as multi-model tab feature)
        $.ajax({
            url: '/generate_comparison_diff',
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({
                original_text: originalText,
                new_text: newText,
                original_model: 'Original',
                new_model: model
            }),
            success: function(diffData) {
                if (typeof diffData === 'string') {
                    try { diffData = JSON.parse(diffData); } catch(e) { diffData = { stats: {}, diff_sections: [] }; }
                }
                var $rendered = renderSemanticDiff(diffData, model);
                $('#compare-diff-view').empty().append($rendered);
                $('#compare-status').text('Complete — switch to ⚡ Diff to see semantic comparison');
            },
            error: function(xhr) {
                $('#compare-diff-view').html('<div class="text-danger p-3">Failed to generate diff: ' + (xhr.responseText || xhr.statusText) + '</div>');
                $('#compare-status').text('Diff generation failed');
            }
        });
    }

    return { open: open };
})();
