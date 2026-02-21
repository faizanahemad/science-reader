/**
 * ContentViewer - Modal module for viewing extracted page content.
 *
 * Manages a Bootstrap 4.6 modal (#content-viewer-modal) that displays
 * extracted content with pagination, word counts, and copy functionality.
 *
 * Public API:
 *   ContentViewer.init()        - Wire up event handlers (call once on DOM ready)
 *   ContentViewer.show(context) - Open the modal with a PageContextManager context object
 *
 * Context object shape expected:
 *   {
 *     content, title, url,
 *     isMultiTab, isOcr, isScreenshot,
 *     tabCount,
 *     sources: [{ title, url, content, contentLength }],
 *     ocrPagesData: [{ index, text }],
 *     mergeType
 *   }
 */

var ContentViewer = (function () {

    /**
     * Internal state for the viewer.
     * @property {Array}   pages        - Array of page text strings
     * @property {number}  currentPage  - Zero-based index of the current page
     * @property {boolean} showingAll   - Whether all pages are shown at once
     * @property {string}  fullText     - Concatenated full text across all pages
     * @property {Array}   originals    - Original page text, set on build for reset
     * @property {Array}   editedFlags  - Boolean array, true if page[i] was edited
     * @property {Object}  _ctx         - Reference to the context object for write-back on close
     * @property {number}  _debounceTimer - Timer id for debounced input handling
     */
    var _state = {
        pages: [],
        currentPage: 0,
        showingAll: false,
        fullText: '',
        originals: [],
        editedFlags: [],
        _ctx: null,
        _debounceTimer: null
    };

    // -------------------------------------------------------------------------
    // Helpers
    // -------------------------------------------------------------------------

    /**
     * Count words in a string.
     *
     * @param {string} text - Input text.
     * @returns {number} Word count.
     */
    function _countWords(text) {
        return text ? text.trim().split(/\s+/).filter(Boolean).length : 0;
    }

    /**
     * Copy text to the clipboard and show a brief toast overlay.
     *
     * @param {string} text - Text to copy.
     */
    function _copyToClipboard(text) {
        if (!navigator.clipboard) {
            showToast('Clipboard not available in this browser.');
            return;
        }
        navigator.clipboard.writeText(text).then(function () {
            var toast = $('<div class="cv-copy-toast">Copied!</div>');
            $('body').append(toast);
            setTimeout(function () {
                toast.remove();
            }, 1500);
        }, function () {
            showToast('Failed to copy to clipboard.');
        });
    }

    // -------------------------------------------------------------------------
    // Page building
    // -------------------------------------------------------------------------

    /**
     * Build the internal pages array from a context object.
     *
     * Handles four cases in priority order:
     *   1. Multi-tab with sources  → one page per source tab
     *   2. OCR with ocrPagesData   → one page per OCR page
     *   3. Multiple sources        → one page per source
     *   4. Single content          → one page with fullText
     *
     * @param {Object} ctx - Context object (see module header for shape).
     */
    function _buildPages(ctx) {
        var pages = [];

        if (ctx.isMultiTab && ctx.sources && ctx.sources.length > 0) {
            // Case 1: multi-tab — one page per source tab
            for (var i = 0; i < ctx.sources.length; i++) {
                var src = ctx.sources[i];
                var header = '## Tab: ' + (src.title || '(no title)') + '\nURL: ' + (src.url || '') + '\n\n';
                pages.push(header + (src.content || ''));
            }
        } else if (ctx.isOcr && ctx.ocrPagesData && ctx.ocrPagesData.length > 0) {
            // Case 2: OCR — one page per OCR page
            for (var j = 0; j < ctx.ocrPagesData.length; j++) {
                var ocrPage = ctx.ocrPagesData[j];
                pages.push(ocrPage.text || '');
            }
        } else if (ctx.sources && ctx.sources.length > 1) {
            // Case 3: multiple sources — one page per source
            for (var k = 0; k < ctx.sources.length; k++) {
                var s = ctx.sources[k];
                var srcHeader = '## ' + (s.title || '(no title)') + '\nURL: ' + (s.url || '') + '\n\n';
                pages.push(srcHeader + (s.content || ''));
            }
        } else {
            // Case 4: single content
            pages.push(ctx.content || '');
        }

        _state.pages = pages;
        _state.currentPage = 0;
        _state.showingAll = false;

        // Snapshot originals for reset and track edit state per page
        _state.originals = pages.slice();
        var flags = [];
        for (var f = 0; f < pages.length; f++) {
            flags.push(false);
        }
        _state.editedFlags = flags;
        _state._ctx = ctx;

        // Build fullText for "copy all" and "show all" modes
        var parts = [];
        for (var p = 0; p < pages.length; p++) {
            parts.push(pages[p]);
        }
        _state.fullText = parts.join('\n\n');
    }

    // -------------------------------------------------------------------------
    // Rendering
    // -------------------------------------------------------------------------

    /**
     * Re-render the modal UI to reflect the current _state.
     * Updates text area, page indicator, char/word counts, and button states.
     */
    function _render() {
        var pages = _state.pages;
        var total = pages.length;
        var idx   = _state.currentPage;
        var all   = _state.showingAll;

        // Determine displayed text
        var displayText;
        if (all) {
            displayText = _state.fullText;
        } else {
            displayText = (total > 0) ? pages[idx] : '';
        }

        // Save scroll position before updating value
        var scrollTop = $('#cv-text').scrollTop();

        // Text area — use .val() for textarea
        $('#cv-text').val(displayText);

        // "All" view is read-only; individual pages are editable
        if (all) {
            $('#cv-text').prop('readonly', true);
        } else {
            $('#cv-text').prop('readonly', false);
        }

        // Restore scroll position
        $('#cv-text').scrollTop(scrollTop);

        // Page indicator
        if (all) {
            $('#cv-page-indicator').text('All ' + total + ' pages');
        } else {
            $('#cv-page-indicator').text('Page ' + (idx + 1) + ' / ' + total);
        }

        // Edited indicator and reset button visibility
        var isEdited = !all && _state.editedFlags[idx];
        if (isEdited) {
            $('#cv-edited-indicator').removeClass('d-none');
            $('#cv-reset-page').removeClass('d-none');
        } else {
            $('#cv-edited-indicator').addClass('d-none');
            $('#cv-reset-page').addClass('d-none');
        }

        // Char / word count
        var chars = displayText ? displayText.length : 0;
        var words = _countWords(displayText);
        $('#cv-char-count').text(chars.toLocaleString() + ' chars | ' + words.toLocaleString() + ' words');

        // Prev / next buttons
        if (all || total <= 1) {
            $('#cv-prev-page').prop('disabled', true);
            $('#cv-next-page').prop('disabled', true);
        } else {
            $('#cv-prev-page').prop('disabled', idx <= 0);
            $('#cv-next-page').prop('disabled', idx >= total - 1);
        }

        // Show-all / paginate toggle button
        $('#cv-show-all').text(all ? 'Paginate' : 'All');

        // Copy-page button label
        if (total <= 1) {
            $('#cv-copy-page').text('Copy');
        } else if (all) {
            $('#cv-copy-page').text('Copy All');
        } else {
            $('#cv-copy-page').text('Copy Page');
        }
    }

    // -------------------------------------------------------------------------
    // Navigation
    // -------------------------------------------------------------------------

    /**
     * Move to an adjacent page.
     *
     * @param {number} delta - +1 for next, -1 for previous.
     */
    function _goToPage(delta) {
        var next = _state.currentPage + delta;
        if (next < 0 || next >= _state.pages.length) {
            return;
        }
        _state.currentPage = next;
        _render();
    }

    /**
     * Toggle between paginated view and all-pages view.
     */
    function _toggleAll() {
        _state.showingAll = !_state.showingAll;
        _render();
    }

    // -------------------------------------------------------------------------
    // Editing
    // -------------------------------------------------------------------------

    /**
     * Handle textarea input. Saves current value to the pages array, marks
     * the page as edited, rebuilds fullText, and updates the char/word counts.
     * Called via debounced handler (500ms) from the textarea input event.
     */
    function _onInput() {
        if (_state.showingAll) {
            return;
        }
        var idx = _state.currentPage;
        var val = $('#cv-text').val();

        _state.pages[idx] = val;
        _state.editedFlags[idx] = true;

        // Rebuild fullText from all pages
        var parts = [];
        for (var i = 0; i < _state.pages.length; i++) {
            parts.push(_state.pages[i]);
        }
        _state.fullText = parts.join('\n\n');

        var chars = val ? val.length : 0;
        var words = _countWords(val);
        $('#cv-char-count').text(chars.toLocaleString() + ' chars | ' + words.toLocaleString() + ' words');

        // Show edited indicators
        $('#cv-edited-indicator').removeClass('d-none');
        $('#cv-reset-page').removeClass('d-none');
    }

    /**
     * Reset the current page to its original text, clearing the edited flag.
     * Restores from _state.originals and re-renders.
     */
    function _resetCurrentPage() {
        var idx = _state.currentPage;
        _state.pages[idx] = _state.originals[idx];
        _state.editedFlags[idx] = false;

        // Rebuild fullText
        var parts = [];
        for (var i = 0; i < _state.pages.length; i++) {
            parts.push(_state.pages[i]);
        }
        _state.fullText = parts.join('\n\n');

        _render();
    }

    /**
     * Write edited pages back to the context object that was passed to show().
     * Called on modal close. Handles multi-tab sources, OCR pages, and single
     * content cases. Strips the header lines that _buildPages prepended for
     * multi-tab/multi-source pages before writing back to ctx.sources[].
     */
    function _saveEditsToContext() {
        var ctx = _state._ctx;
        if (!ctx) {
            return;
        }

        // Check if any page was edited
        var anyEdited = false;
        for (var c = 0; c < _state.editedFlags.length; c++) {
            if (_state.editedFlags[c]) {
                anyEdited = true;
                break;
            }
        }
        if (!anyEdited) {
            return;
        }

        if (ctx.sources && ctx.sources.length > 0 && (_state.pages.length === ctx.sources.length)) {
            // Multi-tab or multi-source: strip header lines before writing back
            for (var i = 0; i < _state.pages.length; i++) {
                if (!_state.editedFlags[i]) {
                    continue;
                }
                var pageText = _state.pages[i];
                // Strip "## Tab: ...\nURL: ...\n\n" or "## ...\nURL: ...\n\n" header
                var headerEnd = pageText.indexOf('\n\n');
                if (headerEnd !== -1 && pageText.substring(0, 3) === '## ') {
                    ctx.sources[i].content = pageText.substring(headerEnd + 2);
                } else {
                    ctx.sources[i].content = pageText;
                }
            }
            // Rebuild merged ctx.content from all sources
            var merged = [];
            for (var m = 0; m < ctx.sources.length; m++) {
                merged.push(ctx.sources[m].content || '');
            }
            ctx.content = merged.join('\n\n');
        } else if (ctx.ocrPagesData && ctx.ocrPagesData.length > 0 && (_state.pages.length === ctx.ocrPagesData.length)) {
            // OCR pages: write text back directly
            for (var j = 0; j < _state.pages.length; j++) {
                if (_state.editedFlags[j]) {
                    ctx.ocrPagesData[j].text = _state.pages[j];
                }
            }
            // Rebuild ctx.content from all OCR pages
            var ocrParts = [];
            for (var o = 0; o < ctx.ocrPagesData.length; o++) {
                ocrParts.push(ctx.ocrPagesData[o].text || '');
            }
            ctx.content = ocrParts.join('\n\n');
        } else {
            // Single content
            ctx.content = _state.pages[0];
        }

        var fullText = ctx.content || '';
        ctx.charCount = fullText.length;
        ctx.wordCount = _countWords(fullText);
    }

    // -------------------------------------------------------------------------
    // Public: show
    // -------------------------------------------------------------------------

    /**
     * Open the content viewer modal for the given context.
     *
     * @param {Object} ctx - PageContextManager context object.
     */
    function show(ctx) {
        ctx = ctx || {};

        // Determine title
        var title;
        if (ctx.isMultiTab && ctx.isOcr) {
            title = 'Multi-Tab Content (OCR)';
        } else if (ctx.isOcr) {
            title = 'OCR Extracted Content';
        } else if (ctx.isScreenshot) {
            title = 'Screenshot Content';
        } else if (ctx.isMultiTab) {
            title = 'Multi-Tab Content';
        } else {
            title = 'Extracted Content';
        }

        $('#cv-title').text(title);

        _buildPages(ctx);
        _render();

        $('#content-viewer-modal').removeClass('d-none');
    }

    // -------------------------------------------------------------------------
    // Init — wire up event handlers
    // -------------------------------------------------------------------------

    /**
     * Initialise the ContentViewer by attaching all event handlers.
     * Must be called once after the DOM is ready.
     */
    function init() {
        // Previous page
        $(document).on('click', '#cv-prev-page', function () {
            _goToPage(-1);
        });

        // Next page
        $(document).on('click', '#cv-next-page', function () {
            _goToPage(1);
        });

        // Toggle all / paginate
        $(document).on('click', '#cv-show-all', function () {
            _toggleAll();
        });

        // Debounced textarea input — saves edits to state
        $(document).on('input', '#cv-text', function () {
            if (_state._debounceTimer) {
                clearTimeout(_state._debounceTimer);
            }
            _state._debounceTimer = setTimeout(function () {
                _onInput();
            }, 500);
        });

        // Reset current page to original
        $(document).on('click', '#cv-reset-page', function () {
            _resetCurrentPage();
        });

        // Copy current page (or all if showingAll)
        $(document).on('click', '#cv-copy-page', function () {
            var text;
            if (_state.showingAll || _state.pages.length <= 1) {
                text = _state.fullText;
            } else {
                text = _state.pages[_state.currentPage] || '';
            }
            _copyToClipboard(text);
        });

        // Copy all pages with dividers
        $(document).on('click', '#cv-copy-all', function () {
            var parts = [];
            for (var i = 0; i < _state.pages.length; i++) {
                parts.push('--- Page ' + (i + 1) + ' ---\n' + _state.pages[i]);
            }
            _copyToClipboard(parts.join('\n\n'));
        });

        // Close button — save edits back to context before hiding
        $(document).on('click', '#cv-close', function () {
            _saveEditsToContext();
            $('#content-viewer-modal').addClass('d-none');
        });

        // Click on modal backdrop (not on .modal-content) → close
        $(document).on('click', '#content-viewer-modal', function (e) {
            if ($(e.target).is('#content-viewer-modal')) {
                _saveEditsToContext();
                $('#content-viewer-modal').addClass('d-none');
            }
        });
    }

    // -------------------------------------------------------------------------
    // Public API
    // -------------------------------------------------------------------------

    return {
        init: init,
        show: show
    };

})();

// Initialise once the DOM is ready
$(document).ready(function () {
    ContentViewer.init();
});
