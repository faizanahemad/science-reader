/**
 * ToolResultInspector
 * -------------------
 * Read-only inspector for complete tool results. Raw output is always available;
 * rendered Markdown is isolated in a sandboxed iframe.
 */
var ToolResultInspector = (function () {
    'use strict';

    var _requestId = 0;
    var _currentText = '';

    function _normaliseText(value) {
        if (value === null || value === undefined) return '';
        if (typeof value === 'string') return value;
        if (typeof value === 'object') {
            try { return JSON.stringify(value, null, 2); } catch (e) { return String(value); }
        }
        return String(value);
    }

    function _formatJsonForDisplay(value) {
        var text = _normaliseText(value);
        try {
            return { text: JSON.stringify(JSON.parse(text), null, 2), isJson: true };
        } catch (e) {
            return { text: text, isJson: false };
        }
    }

    function _formatCount(value) {
        return Number(value || 0).toLocaleString();
    }

    function _escapeHtml(text) {
        return String(text)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function _renderMarkdownPreview(rawText, isJson) {
        var rendered = '<pre>' + _escapeHtml(rawText) + '</pre>';
        if (!isJson && typeof marked !== 'undefined' && marked.parse) {
            try {
                rendered = marked.parse(rawText, { mangle: false, headerIds: false });
            } catch (e) { /* retain escaped raw fallback */ }
        }
        var documentHtml = '<!doctype html><html><head><meta charset="utf-8">' +
            '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'">' +
            '<style>body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;line-height:1.5;margin:16px;overflow-wrap:anywhere}pre{white-space:pre-wrap;word-break:break-word;background:#f8f9fa;padding:12px;border-radius:4px}code{background:#f8f9fa;padding:1px 3px}img{max-width:100%;height:auto}table{border-collapse:collapse;max-width:100%}td,th{border:1px solid #dee2e6;padding:4px}</style>' +
            '</head><body>' + rendered + '</body></html>';
        var frame = document.getElementById('tool-result-inspector-rendered');
        if (frame) frame.srcdoc = documentHtml;
    }

    function _setResult(text, resultChars) {
        var formatted = _formatJsonForDisplay(text);
        var rawText = formatted.text;
        var charCount = (typeof resultChars === 'number' && isFinite(resultChars))
            ? resultChars : rawText.length;
        _currentText = rawText;
        $('#tool-result-inspector-text').val(rawText).scrollTop(0);
        $('#tool-result-inspector-char-count').text(_formatCount(charCount) + ' chars');
        _renderMarkdownPreview(rawText, formatted.isJson);
    }

    function _setLoading() {
        _currentText = '';
        $('#tool-result-inspector-text').val('Loading full tool result…').scrollTop(0);
        $('#tool-result-inspector-char-count').text('Loading…');
        var frame = document.getElementById('tool-result-inspector-rendered');
        if (frame) frame.srcdoc = '';
    }

    function _setError(message) {
        _setResult('Unable to load the full tool result.\n\n' + _normaliseText(message));
    }

    function _copyResult() {
        if (!navigator.clipboard) {
            if (typeof showToast === 'function') showToast('Clipboard not available in this browser.', 'error');
            return;
        }
        navigator.clipboard.writeText(_currentText).then(function () {
            var $button = $('#tool-result-inspector-copy');
            $button.text('Copied');
            setTimeout(function () { $button.text('Copy'); }, 1500);
        }, function () {
            if (typeof showToast === 'function') showToast('Failed to copy tool result.', 'error');
        });
    }

    function _fetchResult(fetchUrl, requestId, metadata) {
        fetch(fetchUrl, { headers: { 'Accept': 'application/json' } })
            .then(function (response) {
                if (!response.ok) throw new Error('HTTP ' + response.status);
                return response.json();
            })
            .then(function (payload) {
                if (requestId !== _requestId) return;
                var result = payload && (payload.result_text !== undefined ? payload.result_text : payload.result);
                _setResult(result, metadata.resultChars !== undefined ? metadata.resultChars : payload.result_chars);
                if (metadata.durationSeconds === undefined && payload.duration_seconds !== undefined) {
                    $('#tool-result-inspector-duration').text(Number(payload.duration_seconds).toFixed(1) + 's');
                }
            })
            .catch(function (error) {
                if (requestId === _requestId) _setError(error && error.message ? error.message : error);
            });
    }

    function open(metadata) {
        metadata = metadata || {};
        var requestId = ++_requestId;
        var toolName = _normaliseText(metadata.toolName || 'Tool');
        var duration = metadata.durationSeconds;
        $('#tool-result-inspector-title').text(toolName + ' Result');
        $('#tool-result-inspector-duration').text(typeof duration === 'number' && isFinite(duration) ? duration.toFixed(1) + 's' : '');
        $('#tool-result-inspector-copy').text('Copy');
        $('#tool-result-inspector-raw-tab').tab('show');
        $('#tool-result-inspector-modal').modal('show');
        if (metadata.resultText !== undefined && metadata.resultText !== null) {
            _setResult(metadata.resultText, metadata.resultChars);
            return;
        }
        if (!metadata.fetchUrl) {
            _setError('No result text or fetch URL was provided.');
            return;
        }
        _setLoading();
        _fetchResult(metadata.fetchUrl, requestId, metadata);
    }

    function init() {
        $(document).on('click', '#tool-result-inspector-copy', _copyResult);
    }

    $(init);
    return { open: open };
})();
