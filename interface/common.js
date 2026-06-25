window.katex = katex;

// ---------------------------------------------------------------------------
// MathJax kill-switch for testing KaTeX-only rendering.
// Set to `true` to skip ALL MathJax typesetting — KaTeX (via marked-katex-extension)
// handles math during markdown parse, so this tests whether MathJax is needed at all.
// Toggle from DevTools console:  window._DISABLE_MATHJAX = true  then reload.
// The flag is set in interface.html <head> before any scripts load; respect it here.
// ---------------------------------------------------------------------------
if (typeof window._DISABLE_MATHJAX === 'undefined') {
    window._DISABLE_MATHJAX = false;
}

// Deferred library initialization — hljs and mermaid are loaded with `defer`,
// so their inline init calls were moved here.  This ready handler registers
// first (common.js is the earliest local script) and therefore fires before
// all other $(document).ready handlers across the codebase.
$(document).ready(function () {
    // highlight.js — scan for any <pre><code> blocks present at DOM-ready.
    // (In practice, code blocks are injected later by renderMessages, so this
    // is usually a no-op.  Kept for forward-compatibility.)
    if (typeof hljs !== 'undefined' && typeof hljs.highlightAll === 'function') {
        hljs.highlightAll();
    }

    // mermaid — configure before any diagrams are rendered.
    if (typeof mermaid !== 'undefined' && typeof mermaid.initialize === 'function') {
        mermaid.initialize({ startOnLoad: true });
    }
});

// --- R4 OPTIMISATION: deferReady utility for non-critical ready handlers ---
// Instead of competing with the main boot sequence for main-thread time during
// $(document).ready, non-critical handlers use requestIdleCallback (with a
// setTimeout(fn, 1) fallback for Safari). The { timeout: 200 } option guarantees
// execution within 200ms even on busy pages. This lets the 3 critical handlers
// (hljs/mermaid config, main boot, sidebar setup) run first, reducing perceived
// boot time by 100-300ms.
//
// Usage: replace `$(document).ready(function() { ... })` with `deferReady(function() { ... })`
// ONLY for handlers classified as deferrable (see next_optimizations_audit.md R4).
window.deferReady = window.requestIdleCallback
    ? function(fn) { $(document).ready(function() { requestIdleCallback(fn, { timeout: 200 }); }); }
    : function(fn) { $(document).ready(function() { setTimeout(fn, 1); }); };

// --- Performance instrumentation utility ---
// Enable with: window._PERF = true  (in browser console before loading a conversation)
// Or set window._PERF = true in chat.js boot sequence for always-on profiling.
//
// Usage:
//   var t = _perfStart('renderMessages');   // starts a performance.mark + console.time
//   ... do work ...
//   _perfEnd('renderMessages', t);          // ends mark, logs duration, creates performance.measure
//
// In Chrome DevTools Performance tab, these show up as named measures in the "Timings" lane.
// In console, they show up as grouped timing summaries.
//
// For per-card tracking:
//   var t = _perfStart('buildCard#' + i);
//   ... build card ...
//   _perfEnd('buildCard#' + i, t);
//
// After a conversation load, call _perfSummary() to print a grouped summary table.
window._PERF = true;  // enabled by default — set to false to silence perf logging
window._perfTimings = {};  // collects {label: [durations...]} for summary

window._perfStart = function(label) {
    if (!window._PERF) return 0;
    try { performance.mark('⏱' + label + '-start'); } catch(e) {}
    return performance.now();
};

window._perfEnd = function(label, startTime) {
    if (!window._PERF || !startTime) return;
    var dur = performance.now() - startTime;
    try {
        performance.mark('⏱' + label + '-end');
        performance.measure('⏱' + label, '⏱' + label + '-start', '⏱' + label + '-end');
    } catch(e) {}
    // Collect for summary
    var base = label.replace(/#\d+$/, '');  // strip card index for grouping
    if (!window._perfTimings[base]) window._perfTimings[base] = [];
    window._perfTimings[base].push(dur);
    return dur;
};

window._perfSummary = function() {
    if (!window._perfTimings || Object.keys(window._perfTimings).length === 0) {
        console.log('[PERF] No timings collected. Set window._PERF = true and load a conversation.');
        return;
    }
    console.group('%c[PERF] Render Pipeline Summary', 'font-weight:bold;color:#2196F3');
    var entries = Object.keys(window._perfTimings).map(function(label) {
        var times = window._perfTimings[label];
        var total = times.reduce(function(a,b) { return a+b; }, 0);
        var avg = total / times.length;
        var max = Math.max.apply(null, times);
        var min = Math.min.apply(null, times);
        return { label: label, count: times.length, total: total, avg: avg, min: min, max: max };
    });
    entries.sort(function(a,b) { return b.total - a.total; });  // sort by total time desc
    console.table(entries.map(function(e) {
        return {
            Label: e.label,
            Count: e.count,
            'Total (ms)': Math.round(e.total),
            'Avg (ms)': Math.round(e.avg * 10) / 10,
            'Min (ms)': Math.round(e.min * 10) / 10,
            'Max (ms)': Math.round(e.max * 10) / 10
        };
    }));
    console.groupEnd();
};

window._perfJSON = function() {
    if (!window._perfTimings || Object.keys(window._perfTimings).length === 0) {
        console.log('[PERF] No timings collected.');
        return '{}';
    }
    var entries = Object.keys(window._perfTimings).map(function(label) {
        var times = window._perfTimings[label];
        var total = times.reduce(function(a,b) { return a+b; }, 0);
        var avg = total / times.length;
        return {
            label: label, count: times.length,
            total_ms: Math.round(total),
            avg_ms: Math.round(avg * 10) / 10,
            min_ms: Math.round(Math.min.apply(null, times) * 10) / 10,
            max_ms: Math.round(Math.max.apply(null, times) * 10) / 10
        };
    });
    entries.sort(function(a,b) { return b.total_ms - a.total_ms; });
    var json = JSON.stringify(entries, null, 2);
    // Copy to clipboard — navigator.clipboard requires document focus, which is
    // lost when typing in DevTools console.  Fall back to the legacy execCommand path.
    try {
        var ta = document.createElement('textarea');
        ta.value = json;
        ta.style.cssText = 'position:fixed;left:-9999px';
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
        console.log('[PERF] Copied to clipboard.');
    } catch(e) { console.log('[PERF] Clipboard copy failed — select the return value manually.'); }
    return json;
};

window._perfReset = function() {
    window._perfTimings = {};
    try { performance.clearMarks(); performance.clearMeasures(); } catch(e) {}
    console.log('[PERF] Timings reset.');
};

// ---------------------------------------------------------------------------
// Yielding MathJax scheduler (R5)
// ---------------------------------------------------------------------------
// MathJax 2's Hub.Queue processes entries back-to-back synchronously — if 40
// Typeset calls are queued at once, the entire batch runs as one giant main-
// thread task ("Processing Math: 100%") that freezes the page for seconds.
//
// This scheduler collects pending Typeset requests and drains them ONE AT A
// TIME, yielding to the browser event loop (setTimeout(0)) between each so
// the page stays scrollable and responsive while math renders progressively.
//
// Usage (drop-in replacement for MathJax.Hub.Queue(["Typeset", ...])):
//   _mathJaxScheduler.enqueue(element, afterCallback, priority)
//   priority = true  → prepend (for the visible/last card)
//   priority = false → append (for deferred/off-screen cards)
//
// During streaming (continuous=true), callers should BYPASS the scheduler and
// call MathJax.Hub.Queue directly — streaming already controls its own pacing.
// ---------------------------------------------------------------------------
window._mathJaxScheduler = (function() {
    var _queue = [];       // [{elem, callback}, ...]
    var _running = false;  // true while draining

    function _drain() {
        if (_queue.length === 0) {
            _running = false;
            return;
        }
        if (typeof MathJax === 'undefined' || !MathJax.Hub) {
            // MathJax not loaded (e.g. _DISABLE_MATHJAX=true) — flush callbacks without typesetting
            var item = _queue.shift();
            if (item.callback) { try { item.callback(); } catch(e) {} }
            setTimeout(_drain, 0);
            return;
        }
        var item = _queue.shift();
        var _t = _perfStart('mathJaxTypeset');
        MathJax.Hub.Queue(["Typeset", MathJax.Hub, item.elem]);
        MathJax.Hub.Queue(function() {
            _perfEnd('mathJaxTypeset', _t);
            if (item.callback) {
                try { item.callback(); } catch(e) {}
            }
            // Yield before processing the next element — this is the key fix.
            // setTimeout(0) lets the browser run paint, scroll, and input handlers
            // between each card's MathJax typeset.
            setTimeout(_drain, 0);
        });
    }

    return {
        enqueue: function(elem, callback, priority) {
            if (priority) {
                _queue.unshift({elem: elem, callback: callback});
            } else {
                _queue.push({elem: elem, callback: callback});
            }
            if (!_running) {
                _running = true;
                // First item: start immediately (no extra delay for the first card)
                _drain();
            }
        },
        /** Discard all pending items (e.g. on conversation switch). */
        clear: function() {
            _queue = [];
        },
        /** Number of items waiting. */
        pending: function() { return _queue.length; }
    };
})();

// Keep this aligned with `CACHE_VERSION` in `interface/service-worker.js` when you want
// deterministic invalidation of cached UI assets and rendered-state snapshots.
window.UI_CACHE_VERSION = "v24";
var currentDomain = {
    domain: 'assistant', // finchat, search
    page_loaded: false,
    manual_domain_change: false,
}

var allDomains = ['finchat', 'search', 'assistant'];
var MOCK_SECTION_STATE_API = false; // If true, skip section state API calls and default sections to hidden

// -----------------------------
// Table of Contents (ToC) config
// -----------------------------
// If an assistant response is longer than this many words, we show a ToC at the top of the card.
// The ToC is client-generated from rendered headings (h1-h4) and section <details> summaries.
var TOC_WORD_THRESHOLD = 500;
// Throttle ToC regeneration during streaming (ms).
var TOC_UPDATE_THROTTLE_MS = 250;

function slugifyForDomId(text) {
    /**
     * Convert human-readable text to a safe DOM id fragment.
     *
     * @param {string} text
     * @returns {string}
     */
    if (!text) return 'section';
    return String(text)
        .toLowerCase()
        .trim()
        .replace(/<[^>]*>/g, ' ')        // strip any tags
        .replace(/&[a-z]+;/g, ' ')       // drop basic entities
        .replace(/[^a-z0-9\s\-_]/g, '')  // keep safe chars
        .replace(/\s+/g, '-')
        .replace(/-+/g, '-')
        .replace(/^-|-$/g, '') || 'section';
}

function estimateWordCountFromMarkdown(markdownText) {
    /**
     * Rough word count used to decide whether ToC should be shown.
     * We intentionally keep this cheap (it runs frequently during streaming).
     *
     * @param {string} markdownText
     * @returns {number}
     */
    if (!markdownText) return 0;
    var s = String(markdownText);
    // Remove fenced code blocks to avoid massively inflating counts with code.
    s = s.replace(/```[\s\S]*?```/g, ' ');
    // Remove HTML tags that can appear in the stream.
    s = s.replace(/<[^>]*>/g, ' ');
    // Normalize whitespace.
    s = s.replace(/\s+/g, ' ').trim();
    if (!s) return 0;
    return s.split(' ').length;
}

function getOrCreateTocPrefix($card) {
    /**
     * Return a stable prefix for generating unique DOM ids within a message card.
     * Uses message-id if available; otherwise falls back to a card-scoped random id.
     *
     * @param {jQuery} $card
     * @returns {string}
     */
    try {
        var existing = $card.attr('data-toc-prefix');
        if (existing) return existing;

        var messageId = ($card.find('.card-header').attr('message-id') || '').trim();
        var prefix = messageId ? (`m-${messageId}`) : (`m-temp-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`);
        $card.attr('data-toc-prefix', prefix);
        return prefix;
    } catch (e) {
        return `m-temp-${Date.now().toString(36)}`;
    }
}

function ensureMessageTocContainer($cardBody) {
    /**
     * Ensure the ToC container exists at the top of the card body.
     * We keep it OUTSIDE the message render element so showMore() doesn't collapse it.
     *
     * @param {jQuery} $cardBody
     * @returns {jQuery} ToC container
     */
    var $existing = $cardBody.find('> .message-toc-container').first();
    if ($existing.length) return $existing;
    var $toc = $('<div class="message-toc-container" style="display:none;"></div>');
    $cardBody.prepend($toc);
    return $toc;
}

function buildTocItemsFromCard($cardBody, tocPrefix) {
    /**
     * Build ToC items from headings and section <details> blocks within the card.
     *
     * @param {jQuery} $cardBody
     * @param {string} tocPrefix
     * @returns {Array<{id: string, text: string, level: number, kind: string}>}
     */
    var items = [];
    var used = {};

    function reserveId(base) {
        var id = base;
        var n = 2;
        while (used[id]) {
            id = `${base}-${n}`;
            n++;
        }
        used[id] = true;
        return id;
    }

    // 1) Section details (generated by renderInnerContentAsMarkdown) - stable anchor = details id.
    $cardBody.find('details.section-details').each(function() {
        // Ignore any ToC UI accidentally inside (shouldn't happen due to container placement).
        if ($(this).closest('.message-toc-container').length) return;
        var detailsId = ($(this).attr('id') || '').trim();
        if (!detailsId) return;
        var summaryText = $(this).find('> summary.section-summary').text().trim();
        if (!summaryText) summaryText = 'Section';

        items.push({
            id: detailsId,
            text: summaryText,
            level: 2,
            kind: 'details',
            _el: this
        });
    });

    // 2) Headings (h1-h6) - add ids if missing.
    $cardBody.find('h1, h2, h3, h4, h5, h6').each(function() {
        if ($(this).closest('.message-toc-container').length) return;
        var $h = $(this);
        var tag = ($h.prop('tagName') || '').toLowerCase();
        var level = 2;
        if (tag === 'h1') level = 1;
        else if (tag === 'h2') level = 2;
        else if (tag === 'h3') level = 3;
        else if (tag === 'h4') level = 4;
        else if (tag === 'h5') level = 5;
        else if (tag === 'h6') level = 6;

        var text = $h.text().trim();
        if (!text) return;

        var existingId = ($h.attr('id') || '').trim();
        if (!existingId) {
            var slug = slugifyForDomId(text);
            var base = `${tocPrefix}-${slug}`;
            var newId = reserveId(base);
            $h.attr('id', newId);
            existingId = newId;
        } else {
            // Ensure uniqueness even if the heading already has an id (defensive).
            if (!used[existingId]) used[existingId] = true;
        }

        items.push({
            id: existingId,
            text: text,
            level: level,
            kind: 'heading',
            _el: this
        });
    });

    // IMPORTANT: Ensure ToC ordering matches the actual rendered order in the DOM.
    // We collect details and headings in separate passes (for convenience), but that can
    // produce incorrect ordering (e.g. a later <details> entry appearing before an earlier H1).
    // Sorting by DOM position fixes this deterministically.
    try {
        items.sort(function(a, b) {
            if (!a || !b) return 0;
            var aEl = a._el;
            var bEl = b._el;
            if (!aEl || !bEl || aEl === bEl || !aEl.compareDocumentPosition) return 0;
            var pos = aEl.compareDocumentPosition(bEl);
            if (pos & Node.DOCUMENT_POSITION_FOLLOWING) return -1; // b after a => a before b
            if (pos & Node.DOCUMENT_POSITION_PRECEDING) return 1;  // b before a => a after b
            return 0;
        });
    } catch (e) { /* ignore */ }

    // Remove internal element references before returning (keeps objects clean / serializable).
    for (var i = 0; i < items.length; i++) {
        try { delete items[i]._el; } catch (e) { /* ignore */ }
    }

    return items;
}

function buildFallbackTocItemsFromCard($cardBody, tocPrefix) {
    /**
     * Fallback ToC generator for long answers that have no headings and no section-details.
     * Creates a navigable list from block elements (paragraphs, code blocks, etc.) and assigns ids.
     *
     * @param {jQuery} $cardBody
     * @param {string} tocPrefix
     * @returns {Array<{id: string, text: string, level: number, kind: string}>}
     */
    var items = [];
    var used = {};
    var MAX_ITEMS = 15;

    function reserveId(base) {
        var id = base;
        var n = 2;
        while (used[id]) {
            id = `${base}-${n}`;
            n++;
        }
        used[id] = true;
        return id;
    }

    // We only consider content inside the message body, excluding the ToC container itself.
    // Prefer blocks that represent "sections" in a narrative answer.
    var $candidates = $cardBody
        .children()
        .not('.message-toc-container')
        .find('p, pre, blockquote, ul, ol, table')
        .filter(function() {
            // Exclude candidates inside ToC UI, or inside code block wrappers that are purely UI.
            if ($(this).closest('.message-toc-container').length) return false;
            if ($(this).closest('.code-header, .section-footer').length) return false;
            var t = $(this).text().trim();
            return t.length >= 40; // avoid tiny/noisy blocks
        });

    $candidates.each(function(idx) {
        if (items.length >= MAX_ITEMS) return false; // break

        var $el = $(this);
        var tag = ($el.prop('tagName') || '').toLowerCase();
        var text = $el.text().trim();
        if (!text) return;

        // Choose a label
        var label = text;
        // If paragraph begins with a strong label (common pattern), use it as the title.
        try {
            var $firstStrong = $el.find('strong').first();
            if ($firstStrong.length) {
                var strongText = $firstStrong.text().trim();
                if (strongText && strongText.length >= 4 && strongText.length <= 80) {
                    label = strongText;
                }
            }
        } catch (e) { /* ignore */ }

        // Truncate label
        if (label.length > 60) label = label.slice(0, 57) + '...';

        // Assign/ensure id
        var existingId = ($el.attr('id') || '').trim();
        if (!existingId) {
            var slug = slugifyForDomId(label);
            var base = `${tocPrefix}-auto-${tag}-${idx}-${slug}`;
            existingId = reserveId(base);
            $el.attr('id', existingId);
        } else {
            if (!used[existingId]) used[existingId] = true;
        }

        // Level heuristic: keep these as level 2 so the ToC isn't overly indented
        items.push({
            id: existingId,
            text: label,
            level: 2,
            kind: 'auto'
        });
    });

    return items;
}

function renderMessageToc($tocContainer, items, tocPrefix, expanded) {
    /**
     * Render ToC UI into container.
     *
     * @param {jQuery} $tocContainer
     * @param {Array} items
     * @param {string} tocPrefix
     * @param {boolean} expanded - If true, show expanded ToC. If false, show collapsed with item count.
     *                            Default: true (expanded) for backward compatibility.
     */
    if (expanded === undefined) expanded = true;
    
    if (!items || items.length === 0) {
        $tocContainer.hide().empty();
        return;
    }

    var itemCount = items.length;
    var buttonText = expanded ? 'Hide' : 'Show (' + itemCount + ')';
    var bodyStyle = expanded ? '' : ' style="display:none;"';
    
    var html = '';
    html += `<div class="message-toc card" data-toc-prefix="${tocPrefix}" data-toc-expanded="${expanded}">`;
    html += `  <div class="message-toc-header d-flex justify-content-between align-items-center">`;
    html += `    <div><strong>Table of Contents</strong></div>`;
    html += `    <button class="btn btn-xs btn-secondary message-toc-toggle" type="button" data-toc-action="toggle">${buttonText}</button>`;
    html += `  </div>`;
    html += `  <div class="message-toc-body"${bodyStyle}>`;
    html += `    <ul class="message-toc-list">`;

    items.forEach(function(it) {
        var indent = Math.max(0, Math.min(3, (it.level || 2) - 1)); // cap at 3
        var safeText = String(it.text || '').replace(/</g, '&lt;').replace(/>/g, '&gt;');
        html += `      <li class="message-toc-item indent-${indent}">`;
        html += `        <a href="#${it.id}" class="message-toc-link" data-toc-target="${it.id}">${safeText}</a>`;
        html += `      </li>`;
    });

    html += `    </ul>`;
    html += `  </div>`;
    html += `</div>`;

    // Only reveal the container when the message body is not currently collapsed
    // and compact-nav mode is not active.
    var $moreText = $tocContainer.closest('.card-body').find('.more-text').first();
    var _tocCompact = document.body.classList.contains('compact-nav');
    if ($moreText.length > 0 && !$moreText.is(':visible')) {
        $tocContainer.html(html); // message is collapsed — keep container hidden
    } else if (_tocCompact) {
        // Compact mode: show the header bar but collapse the body list
        $tocContainer.html(html).show();
        _tocCollapseForCompact($tocContainer);
    } else {
        $tocContainer.html(html).show();
    }
}

// ---------------------------------------------------------------------------
// TOC compact-nav helpers
// Used by renderMessageToc, decorateMessageCardNav, applyConversationUIState,
// and applyCompactNav (chat.js) to collapse / restore TOC bodies without
// fully hiding the container (so the "Table of Contents [Show N]" bar stays
// visible in compact mode).
// ---------------------------------------------------------------------------

/**
 * Collapse the TOC body while keeping the header bar visible.
 * Marks the .message-toc with data-compact-auto-collapsed so the restore
 * helper can tell apart user-intentional collapses from automatic ones.
 */
function _tocCollapseForCompact($container) {
    if (!$container || !$container.length || $container.children().length === 0) return;
    var $msgToc = $container.find('.message-toc').first();
    if (!$msgToc.length) return;
    $container.show(); // ensure container itself is visible
    if ($msgToc.attr('data-toc-expanded') !== 'false') {
        var n = $msgToc.find('.message-toc-item').length;
        $msgToc.find('.message-toc-body').hide();
        $msgToc.find('.message-toc-toggle').text('Show (' + n + ')');
        $msgToc.attr('data-toc-expanded', 'false');
        $msgToc.attr('data-compact-auto-collapsed', 'true');
    } else {
        // Already collapsed (user or prior pass) — just keep container visible
        $container.show();
    }
}

/**
 * Restore a TOC that was auto-collapsed by compact mode.
 * Only expands when data-compact-auto-collapsed is set; leaves user-intentional
 * collapses untouched.
 */
function _tocRestoreFromCompact($container) {
    if (!$container || !$container.length) return;
    var $msgToc = $container.find('.message-toc').first();
    if ($msgToc.length && $msgToc.attr('data-compact-auto-collapsed') === 'true') {
        $msgToc.find('.message-toc-body').show();
        $msgToc.find('.message-toc-toggle').text('Hide');
        $msgToc.attr('data-toc-expanded', 'true');
        $msgToc.removeAttr('data-compact-auto-collapsed');
    }
}

function updateMessageTocForElement(elem_to_render_in, rawMarkdown, continuous = false) {
    /**
     * Update (or hide) the ToC for the message card containing elem_to_render_in.
     * Safe to call frequently; internally throttled.
     *
     * Expanded state logic (3-way):
     * 1. Historic render (no streaming flags): expanded = true
     * 2. Live streaming (data-live-stream="true"): expanded = false, unless user already expanded
     * 3. Post-streaming (data-live-stream-ended="true"): keep current state (collapsed unless user expanded)
     *
     * @param {HTMLElement|jQuery} elem_to_render_in
     * @param {string} rawMarkdown
     * @param {boolean} continuous - true when called during streaming/incremental renders
     */
    var $elem = $(elem_to_render_in);
    if (!$elem || $elem.length === 0) return;

    var $card = $elem.closest('.card');
    var $cardBody = $elem.closest('.card-body');
    if ($card.length === 0 || $cardBody.length === 0) return;

    // Throttle ONLY during continuous (streaming) renders.
    // For final/non-continuous renders, always compute ToC so it reliably appears after streaming completes.
    var now = Date.now();
    if (continuous) {
        var last = parseInt($card.attr('data-toc-last-update') || '0', 10);
        if (now - last < TOC_UPDATE_THROTTLE_MS) return;
        $card.attr('data-toc-last-update', String(now));
    }

    // Word count strategy:
    // Use the entire card content (excluding ToC UI) for BOTH streaming and non-streaming.
    // This prevents "chunk-sized" word counts from keeping ToC hidden during streaming and
    // avoids ToC disappearing when later chunks are small.
    var $tabsContainer = $cardBody.attr('data-has-tabs') ? $cardBody.find('.model-tabs-container').first() : $();
    if ($tabsContainer.length > 0) {
        // ToC should not render when the tabs container is present.
        // In a tabbed response we render per-tab ToC via updateMessageTocForTabs.
        ensureMessageTocContainer($cardBody).hide().empty();
        updateMessageTocForTabs($tabsContainer, rawMarkdown, continuous);

        // If floating ToC is open for this card, update it with the active tab's items.
        try {
            if ($card.attr('data-floating-toc-open') === 'true') {
                var tocPrefix = getOrCreateTocPrefix($card);
                var $activePane = $tabsContainer.find('.tab-pane.active').first();
                var $activeBody = $activePane.find('> .model-tab-body');
                var tabIndex = $tabsContainer.find('.tab-pane').index($activePane);
                if (tabIndex < 0) tabIndex = 0;

                var panePrefix = tocPrefix + '-tab-' + tabIndex;
                var items = buildTocItemsFromCard($activeBody.length ? $activeBody : $activePane, panePrefix);
                if (!items || items.length === 0) {
                    items = buildFallbackTocItemsFromCard($activeBody.length ? $activeBody : $activePane, panePrefix);
                }
                updateFloatingTocIfOpen($card, items || [], panePrefix);
            }
        } catch (e) { /* ignore */ }
        return;
    }

    var contentText = '';
    try {
        contentText = $cardBody.children().not('.message-toc-container').text();
    } catch (e) {
        contentText = $cardBody.text();
    }
    var wordCount = estimateWordCountFromMarkdown(contentText || rawMarkdown || '');
    var $tocContainer = ensureMessageTocContainer($cardBody);

    if (wordCount < TOC_WORD_THRESHOLD) {
        $tocContainer.hide().empty();
        return;
    }

    var tocPrefix = getOrCreateTocPrefix($card);
    var items = buildTocItemsFromCard($cardBody, tocPrefix);
    if (!items || items.length === 0) {
        // Fallback: if the answer is long but doesn't use headings/--- sections,
        // generate a ToC from block elements so users can still navigate.
        items = buildFallbackTocItemsFromCard($cardBody, tocPrefix);
    }
    if (!items || items.length === 0) {
        $tocContainer.hide().empty();
        return;
    }
    
    // Determine expanded state using 3-way logic
    var expanded = determineTocExpandedState($card, $tocContainer);
    
    renderMessageToc($tocContainer, items, tocPrefix, expanded);
    
    // Also update floating ToC if it's open for this card
    updateFloatingTocIfOpen($card, items, tocPrefix);
}

/**
 * Determine whether the ToC should be rendered expanded or collapsed.
 * 
 * 3-way logic:
 * 1. Historic render (no streaming flags): expanded = true (backward compat)
 * 2. Live streaming (data-live-stream="true"): expanded = false, unless user already expanded
 * 3. Post-streaming (data-live-stream-ended="true"): keep current state (collapsed unless user expanded)
 *
 * @param {jQuery} $card - The message card
 * @param {jQuery} $tocContainer - The ToC container (to check current expanded state)
 * @returns {boolean} true if expanded, false if collapsed
 */
function determineTocExpandedState($card, $tocContainer) {
    // Check if user has explicitly expanded the ToC
    var userExpanded = $card.attr('data-toc-user-expanded') === 'true';
    if (userExpanded) {
        return true;
    }
    
    // Check streaming state flags
    var isLiveStreaming = $card.attr('data-live-stream') === 'true';
    var isPostStreaming = $card.attr('data-live-stream-ended') === 'true';
    
    if (isLiveStreaming) {
        // During live streaming: collapsed by default
        return false;
    } else if (isPostStreaming) {
        // After streaming ended: keep current state
        // If ToC already exists, preserve its current expanded state
        var $existingToc = $tocContainer.find('.message-toc');
        if ($existingToc.length > 0) {
            var currentExpanded = $existingToc.attr('data-toc-expanded');
            if (currentExpanded !== undefined) {
                return currentExpanded === 'true';
            }
        }
        // Default to collapsed if no previous state
        return false;
    } else {
        // Historic render (no streaming flags): expanded by default (backward compat)
        return true;
    }
}

function updateMessageTocForTabs($tabsContainer, rawMarkdown, continuous = false) {
    /**
     * Render per-tab ToC inside a tabbed response container.
     * For tabbed responses, the expanded state is tracked per tab-pane.
     *
     * @param {jQuery} $tabsContainer
     * @param {string} rawMarkdown
     * @param {boolean} continuous
     */
    if (!$tabsContainer || $tabsContainer.length === 0) return;
    var $card = $tabsContainer.closest('.card');
    var $cardBody = $tabsContainer.closest('.card-body');
    if ($card.length === 0 || $cardBody.length === 0) return;

    var now = Date.now();
    if (continuous) {
        var last = parseInt($card.attr('data-toc-last-update') || '0', 10);
        if (now - last < TOC_UPDATE_THROTTLE_MS) return;
        $card.attr('data-toc-last-update', String(now));
    }

    var tocPrefix = getOrCreateTocPrefix($card);
    var $panes = $tabsContainer.find('> .tab-content > .tab-pane');
    var anyRendered = false;

    $panes.each(function(idx, pane) {
        var $pane = $(pane);
        var $body = $pane.find('> .model-tab-body');
        if ($body.length === 0) return;

        var contentText = '';
        try {
            contentText = $body.text();
        } catch (e) {
            contentText = $pane.text();
        }
        var wordCount = estimateWordCountFromMarkdown(contentText || rawMarkdown || '');

        // Preserve existing ToC container's expanded state before removing
        var $existingTocContainer = $pane.find('.message-toc-container').first();
        var existingExpanded = null;
        if ($existingTocContainer.length > 0) {
            var $existingToc = $existingTocContainer.find('.message-toc');
            if ($existingToc.length > 0) {
                existingExpanded = $existingToc.attr('data-toc-expanded');
            }
        }
        
        $pane.find('.message-toc-container').remove();
        var $tocContainer = $('<div class="message-toc-container" style="display:none;"></div>');
        $pane.prepend($tocContainer);

        if (wordCount < TOC_WORD_THRESHOLD) {
            $tocContainer.hide().empty();
            return;
        }

        var panePrefix = tocPrefix + '-tab-' + idx;
        var items = buildTocItemsFromCard($body, panePrefix);
        if (!items || items.length === 0) {
            items = buildFallbackTocItemsFromCard($body, panePrefix);
        }
        if (!items || items.length === 0) {
            $tocContainer.hide().empty();
            return;
        }
        
        // Determine expanded state for this tab-pane
        var expanded = determineTocExpandedStateForPane($card, $pane, $tocContainer, existingExpanded);
        
        renderMessageToc($tocContainer, items, panePrefix, expanded);
        anyRendered = true;
    });

    if (anyRendered) {
        try {
            ensureMessageTocContainer($cardBody).hide().empty();
        } catch (e) { /* ignore */ }
    }
}

/**
 * Determine whether the ToC should be rendered expanded or collapsed for a tab-pane.
 * For tabbed responses, the state is tracked per tab-pane.
 *
 * @param {jQuery} $card - The message card
 * @param {jQuery} $pane - The tab-pane
 * @param {jQuery} $tocContainer - The ToC container
 * @param {string|null} existingExpanded - Previous expanded state ('true'/'false') if any
 * @returns {boolean} true if expanded, false if collapsed
 */
function determineTocExpandedStateForPane($card, $pane, $tocContainer, existingExpanded) {
    // Check if user has explicitly expanded the ToC in this pane
    var userExpanded = $pane.attr('data-toc-user-expanded') === 'true';
    if (userExpanded) {
        return true;
    }

    // Pane nodes can be rebuilt during streaming tab re-renders (applyModelResponseTabs),
    // so also honor the card-level preference if present.
    try {
        if ($card && $card.length > 0 && $card.attr('data-toc-user-expanded') === 'true') {
            return true;
        }
    } catch (e) { /* ignore */ }
    
    // Check streaming state flags on the card
    var isLiveStreaming = $card.attr('data-live-stream') === 'true';
    var isPostStreaming = $card.attr('data-live-stream-ended') === 'true';
    
    if (isLiveStreaming) {
        // During live streaming: collapsed by default
        return false;
    } else if (isPostStreaming) {
        // After streaming ended: keep current state
        if (existingExpanded !== null && existingExpanded !== undefined) {
            return existingExpanded === 'true';
        }
        // Default to collapsed if no previous state
        return false;
    } else {
        // Historic render (no streaming flags): expanded by default (backward compat)
        return true;
    }
}

// ToC interactions: toggle and scroll (expanding showMore and <details> if needed)
$(document)
    .off('click', '.message-toc-toggle')
    .on('click', '.message-toc-toggle', function(e) {
        e.preventDefault();
        e.stopPropagation();
        var $toc = $(this).closest('.message-toc');
        var $body = $toc.find('.message-toc-body');
        var isVisible = $body.is(':visible');
        var itemCount = $toc.find('.message-toc-item').length;
        
        // Find the card or tab-pane to persist expanded state
        var $tabPane = $toc.closest('.tab-pane');
        var $card = $toc.closest('.card.message-card');
        var $stateContainer = $tabPane.length > 0 ? $tabPane : $card;
        
        if (isVisible) {
            $body.hide();
            $(this).text('Show (' + itemCount + ')');
            $toc.attr('data-toc-expanded', 'false');
            // If user collapses after expanding, clear the "user expanded" preference so it can stay collapsed.
            if ($stateContainer.length > 0) {
                $stateContainer.removeAttr('data-toc-user-expanded');
            }
            // Also clear card-level preference so rebuilt tab panes won't re-expand during streaming.
            if ($card.length > 0) {
                $card.removeAttr('data-toc-user-expanded');
            }
        } else {
            $body.show();
            $(this).text('Hide');
            $toc.attr('data-toc-expanded', 'true');
            // Mark that user has explicitly expanded the ToC - this persists through streaming updates
            if ($stateContainer.length > 0) {
                $stateContainer.attr('data-toc-user-expanded', 'true');
            }
            // Persist at card-level too (stable across tab pane rebuilds during streaming).
            if ($card.length > 0) {
                $card.attr('data-toc-user-expanded', 'true');
            }
        }
    })
    .off('click', '.message-toc-link')
    .on('click', '.message-toc-link', function(e) {
        // We control navigation to reliably expand containers before scrolling.
        e.preventDefault();
        e.stopPropagation();

        var targetId = $(this).attr('data-toc-target');
        if (!targetId) return;

        var $card = $(this).closest('.card');
        // Expand showMore() if the message is currently collapsed.
        try {
            var $moreText = $card.find('.more-text').first();
            if ($moreText.length && !$moreText.is(':visible')) {
                // Click the first show-more toggle in this card.
                var $toggle = $card.find('.show-more').first();
                if ($toggle.length) $toggle.trigger('click');
            }
        } catch (err) { /* ignore */ }

        // Expand any <details> ancestors of the target.
        var targetEl = document.getElementById(targetId);
        if (!targetEl) {
            // Update hash anyway (useful for shareability) even if not found yet.
            window.location.hash = targetId;
            return;
        }

        try {
            var el = targetEl;
            while (el) {
                if (el.tagName && el.tagName.toLowerCase() === 'details') {
                    el.open = true;
                }
                el = el.parentElement;
            }
        } catch (err) { /* ignore */ }

        // Scroll into view and update URL hash.
        try { targetEl.scrollIntoView({ behavior: 'smooth', block: 'start' }); } catch (err) {}
        try { window.location.hash = targetId; } catch (err) {}
    });

// ============================================
// Floating ToC Panel (Solution 7)
// ============================================

/**
 * Show a floating ToC panel for the given card element.
 * The floating panel is positioned relative to the card and provides
 * an alternative way to navigate long responses.
 *
 * @param {jQuery} $cardElem - The card element to show ToC for
 */
function showFloatingToc($cardElem) {
    var $card = $($cardElem);
    if (!$card || $card.length === 0) {
        showToast('Unable to find message card', 'warning');
        return;
    }
    
    // Close any existing floating ToC panels
    closeAllFloatingTocs();
    
    var $cardBody = $card.find('.card-body').first();
    if ($cardBody.length === 0) {
        showToast('Message content not found', 'warning');
        return;
    }
    
    // Determine if this is a tabbed response and get the active tab's content
    var $tabsContainer = $cardBody.attr('data-has-tabs') ? $cardBody.find('.model-tabs-container').first() : $();
    var $targetContent = $cardBody;
    var tocPrefix = getOrCreateTocPrefix($card);
    
    if ($tabsContainer.length > 0) {
        // For tabbed responses, get the active tab's content
        var $activePane = $tabsContainer.find('.tab-pane.active').first();
        if ($activePane.length > 0) {
            var $activeBody = $activePane.find('> .model-tab-body');
            if ($activeBody.length > 0) {
                $targetContent = $activeBody;
                var tabIndex = $tabsContainer.find('.tab-pane').index($activePane);
                tocPrefix = tocPrefix + '-tab-' + tabIndex;
            }
        }
    }
    
    // Build ToC items
    var items = buildTocItemsFromCard($targetContent, tocPrefix);
    if (!items || items.length === 0) {
        items = buildFallbackTocItemsFromCard($targetContent, tocPrefix);
    }
    
    if (!items || items.length === 0) {
        showToast('No table of contents available for this message', 'info');
        return;
    }
    
    // Create the floating panel
    var panelHtml = buildFloatingTocPanelHtml(items, tocPrefix);
    var $panel = $(panelHtml);
    
    // Position the panel relative to the card
    $card.css('position', 'relative');
    $card.append($panel);
    
    // Store reference on card for updates
    $card.attr('data-floating-toc-open', 'true');
    
    // Set up event handlers for the floating panel
    setupFloatingTocHandlers($panel, $card);
    
    // Animate the panel in
    requestAnimationFrame(function() {
        $panel.addClass('floating-toc-visible');
    });
}

/**
 * Build the HTML for the floating ToC panel.
 *
 * @param {Array} items - ToC items from buildTocItemsFromCard
 * @param {string} tocPrefix - Prefix for this card's ToC
 * @returns {string} HTML string for the panel
 */
function buildFloatingTocPanelHtml(items, tocPrefix) {
    var html = '';
    html += '<div class="floating-toc-panel" data-toc-prefix="' + tocPrefix + '">';
    html += '  <div class="floating-toc-header d-flex justify-content-between align-items-center">';
    html += '    <span><strong>Contents</strong></span>';
    html += '    <button class="btn btn-xs btn-secondary floating-toc-close" type="button">&times;</button>';
    html += '  </div>';
    html += '  <div class="floating-toc-body">';
    html += '    <ul class="floating-toc-list">';
    
    items.forEach(function(it) {
        var indent = Math.max(0, Math.min(3, (it.level || 2) - 1));
        var safeText = String(it.text || '').replace(/</g, '&lt;').replace(/>/g, '&gt;');
        html += '      <li class="floating-toc-item indent-' + indent + '">';
        html += '        <a href="#' + it.id + '" class="floating-toc-link" data-toc-target="' + it.id + '">' + safeText + '</a>';
        html += '      </li>';
    });
    
    html += '    </ul>';
    html += '  </div>';
    html += '</div>';
    
    return html;
}

/**
 * Set up event handlers for the floating ToC panel.
 *
 * @param {jQuery} $panel - The floating panel element
 * @param {jQuery} $card - The card element containing the panel
 */
function setupFloatingTocHandlers($panel, $card) {
    // Close button
    $panel.find('.floating-toc-close').on('click', function(e) {
        e.preventDefault();
        e.stopPropagation();
        closeFloatingToc($card);
    });
    
    // ToC link clicks — delegated on $panel so the handler survives $body.html()
    // replacements during streaming. updateFloatingTocIfOpen replaces .floating-toc-body
    // innerHTML on every throttled chunk, destroying and recreating all <a> elements.
    // A direct .find(...).on() would bind to dead nodes after the first update. By
    // delegating on $panel (which is stable for the full panel lifetime), we set up
    // exactly one handler at open-time and never need to rebind.
    //
    // Also fixes a correctness gap vs the old updateFloatingTocIfOpen handler: when
    // targetEl is null (heading not yet in DOM during streaming), this version falls
    // back to window.location.hash so the browser updates the URL and doesn't silently
    // do nothing.
    $panel.on('click', '.floating-toc-link', function(e) {
        e.preventDefault();
        e.stopPropagation();
        
        var targetId = $(this).attr('data-toc-target');
        if (!targetId) return;
        
        // Expand showMore() if the message is currently collapsed
        try {
            var $moreText = $card.find('.more-text').first();
            if ($moreText.length && !$moreText.is(':visible')) {
                var $toggle = $card.find('.show-more').first();
                if ($toggle.length) $toggle.trigger('click');
            }
        } catch (err) { /* ignore */ }
        
        // Expand any <details> ancestors of the target
        var targetEl = document.getElementById(targetId);
        if (!targetEl) {
            // Heading not in DOM yet (streaming in progress) — update hash only
            window.location.hash = targetId;
            return;
        }
        
        try {
            var el = targetEl;
            while (el) {
                if (el.tagName && el.tagName.toLowerCase() === 'details') {
                    el.open = true;
                }
                el = el.parentElement;
            }
        } catch (err) { /* ignore */ }
        
        // Scroll into view and update URL hash
        try { targetEl.scrollIntoView({ behavior: 'smooth', block: 'start' }); } catch (err) {}
        try { window.location.hash = targetId; } catch (err) {}
    });
    
    // Strip any previously accumulated document-level handlers for this namespace
    // before re-registering. closeAllFloatingTocs() also calls .off(), but the
    // click.floatingToc handler is registered inside a setTimeout(100ms), so a
    // rapid re-open within that window would bypass that cleanup and stack a
    // duplicate. Calling .off() here — synchronously, before the setTimeout —
    // closes the race window entirely. jQuery .off() on an unbound namespace is
    // a no-op, so this is safe regardless of prior state.
    $(document).off('click.floatingToc');
    $(document).off('keydown.floatingToc');

    // Close on click outside (after a short delay to avoid closing immediately)
    setTimeout(function() {
        $(document).on('click.floatingToc', function(e) {
            if (!$(e.target).closest('.floating-toc-panel').length && 
                !$(e.target).closest('.floating-toc-trigger').length) {
                closeAllFloatingTocs();
            }
        });
    }, 100);
    
    // Close on escape key
    $(document).on('keydown.floatingToc', function(e) {
        if (e.key === 'Escape') {
            closeAllFloatingTocs();
        }
    });
}

/**
 * Close the floating ToC panel for a specific card.
 *
 * @param {jQuery} $card - The card element
 */
function closeFloatingToc($card) {
    var $panel = $card.find('.floating-toc-panel');
    if ($panel.length === 0) return;
    
    $panel.removeClass('floating-toc-visible');
    
    // Remove after animation
    setTimeout(function() {
        $panel.remove();
        $card.removeAttr('data-floating-toc-open');
    }, 200);
}

/**
 * Close all floating ToC panels and clean up event handlers.
 */
function closeAllFloatingTocs() {
    $('.floating-toc-panel').each(function() {
        var $panel = $(this);
        var $card = $panel.closest('.card.message-card');
        $panel.removeClass('floating-toc-visible');
        
        setTimeout(function() {
            $panel.remove();
            if ($card.length) {
                $card.removeAttr('data-floating-toc-open');
            }
        }, 200);
    });
    
    // Clean up document-level event handlers
    $(document).off('click.floatingToc');
    $(document).off('keydown.floatingToc');
}

/**
 * Update the floating ToC panel if it's open.
 * Called during streaming updates to keep floating ToC in sync.
 *
 * @param {jQuery} $card - The card element
 * @param {Array} items - New ToC items
 * @param {string} tocPrefix - ToC prefix
 */
function updateFloatingTocIfOpen($card, items, tocPrefix) {
    if ($card.attr('data-floating-toc-open') !== 'true') return;
    
    var $panel = $card.find('.floating-toc-panel');
    if ($panel.length === 0) return;
    
    if (!items || items.length === 0) {
        closeFloatingToc($card);
        return;
    }
    
    // Update the panel body with new items
    var html = '<ul class="floating-toc-list">';
    items.forEach(function(it) {
        var indent = Math.max(0, Math.min(3, (it.level || 2) - 1));
        var safeText = String(it.text || '').replace(/</g, '&lt;').replace(/>/g, '&gt;');
        html += '<li class="floating-toc-item indent-' + indent + '">';
        html += '  <a href="#' + it.id + '" class="floating-toc-link" data-toc-target="' + it.id + '">' + safeText + '</a>';
        html += '</li>';
    });
    html += '</ul>';
    
    var $body = $panel.find('.floating-toc-body');
    $body.html(html);
    // Click handlers are on $panel via delegation (setupFloatingTocHandlers) — no
    // rebinding needed after $body.html() replaces the <a> elements.
}

// Close floating ToC when switching conversations
$(document).on('conversationChanged', closeAllFloatingTocs);

async function responseWaitAndSuccessChecker(url, responsePromise) {
    // Set a timeout for the API call
    const apiTimeout = setTimeout(() => {
        alert(`The API at ${url} took too long to respond. Reloading the page is advised.`);
        // Reload the page after 5 seconds
        setTimeout(() => {
            location.reload();
        }, 6000);
    }, 480000);  // 8 minute timeout

    try {
        // Wait for the API response
        const response = await responsePromise;

        // Clear the timeout as the API responded
        clearTimeout(apiTimeout);

        // Check the API response status
        if (!response.ok) {
            alert(`An error occurred while calling ${url}: ${response.status}. Reloading the page is advised.`);
            // Reload the page after 5 seconds
            setTimeout(() => {
                location.reload();
            }, 6000);
            return;
        }

        // You can add further code here to process the response if it's OK
        // ...
    } catch (error) {
        // Clear the timeout as an error occurred
        clearTimeout(apiTimeout);

        alert(`An error occurred while calling ${url}: ${error.toString()}. Reloading the page is advised.`);
        // Reload the page after 5 seconds
        setTimeout(() => {
            location.reload();
        }, 6000);
    }
}

function getMimeType(file) {
    var extension = file.name.split('.').pop().toLowerCase();
    var mimeTypeMap = {
        'pdf': 'application/pdf',
        'doc': 'application/msword',
        'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'txt': 'text/plain',
        'jpeg': 'image/jpeg',
        'jpg': 'image/jpeg',
        'png': 'image/png',
        'svg': 'image/svg+xml',
        'bmp': 'image/bmp',
        'rtf': 'application/rtf',
        'xls': 'application/vnd.ms-excel',
        'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'csv': 'text/csv',
        'tsv': 'text/tab-separated-values',
        'parquet': 'application/parquet',
        'json': 'application/json',
        'jsonl': 'application/x-jsonlines',
        'ndjson': 'application/x-ndjson',
        'mp3': 'audio/mpeg',
        'mpeg': 'audio/mpeg',
        'wav': 'audio/wav',
        'wave': 'audio/wav',
        'm4a': 'audio/mp4',
        'aac': 'audio/aac',
        'flac': 'audio/flac',
        'xflac': 'audio/x-flac',
        'ogg': 'audio/ogg',
        'oga': 'audio/ogg',
        'opus': 'audio/opus',
        'webm': 'audio/webm',
        'wma': 'audio/x-ms-wma',
        'aiff': 'audio/aiff',
        'aif': 'audio/aiff',
        'aifc': 'audio/aiff',
        'mp4': 'video/mp4'
    };
    return mimeTypeMap[extension] || 'application/octet-stream'; // Default MIME type  
}  

function getFileType(file, callback) {
    var filetypedict = {};
    var reader = new FileReader();
    reader.onload = function (e) {
        var mimeType = e.target.result.match(/data:([^;]*);/)[1];
        filetypedict["mimeType"] = mimeType;
        callback(mimeType); // Pass the MIME type to the callback function  
    };
    reader.onerror = function (e) {
        console.error("Error reading file:", e);
        callback(null); // Pass null to the callback in case of an error  
    };
    reader.readAsDataURL(file);
    return filetypedict;
}  


function addNewlineToTextbox(textboxId) {
    var messageText = $('#' + textboxId);
    var cursorPos = messageText.prop('selectionStart');
    var v = messageText.val();
    var textBefore = v.substring(0, cursorPos);
    var textAfter = v.substring(cursorPos, v.length);
    messageText.val(textBefore + '\n' + textAfter);
    messageText.prop('selectionStart', cursorPos + 1);
    messageText.prop('selectionEnd', cursorPos + 1);
    // Auto-scroll textarea to bottom when adding newline at end
    if (textAfter.length === 0) {
        var scrollHeight = messageText.prop('scrollHeight');
        messageText.scrollTop(scrollHeight);
    }
    return false;  // Prevents the default action
}

// This function sets the max-height based on the line height
function setMaxHeightForTextbox(textboxId, height = 10) {
    var messageText = $('#' + textboxId);

    // Determine the line height (might not always be precise, but close)
    var lineHeight;
    try {
        lineHeight = parseFloat(getComputedStyle(messageText[0]).lineHeight);
    } catch (e) {
        // Default to 20px line height if computation fails
        lineHeight = 20;
        // [DEBUG] console.log("Could not compute line height, using default value of 20px");
    }

    // Set max-height for 10 lines
    if (!height) {
        height = 10;
    }
    var maxHeight = lineHeight * height;
    messageText.css('max-height', maxHeight + 'px');

    // Set overflow to auto to ensure scrollbars appear if needed
    messageText.css('overflow-y', 'auto');
}

// Scroll preservation helpers
// NOTE: Preserving a raw scrollTop value is often insufficient when we insert/remove DOM above the
// user's viewport (e.g., when building Main/TLDR tabs). In those cases, keeping the same scrollTop
// can still "shift" the visible content. Instead, we capture an on-screen anchor and keep it at
// the same viewport offset after DOM changes.
function captureChatViewScrollAnchor($chatView) {
    /**
     * Capture a "visual anchor" inside #chatView so we can restore the same content position
     * after large DOM rewrites (innerHTML, tab-building, showMore(), etc.).
     *
     * We attempt to capture:
     * - a stable element id (preferably a heading/section id) visible near the top of the viewport
     * - fallback: message-id of the card header + pixel offset within that card
     */
    try {
        if (!$chatView || $chatView.length === 0 || !$chatView[0]) return null;
        var container = $chatView[0];
        var rect = container.getBoundingClientRect();
        if (!rect || rect.width <= 0 || rect.height <= 0) return null;

        // Pick a point near the top third of the viewport, away from left gutters.
        var x = rect.left + Math.min(80, rect.width * 0.5);
        var y = rect.top + Math.min(140, rect.height * 0.33);
        var el = document.elementFromPoint(x, y);
        if (!el) return null;
        if (!container.contains(el)) return null;

        var $el = $(el);
        var $card = $el.closest('.card.message-card');
        var messageId = '';
        if ($card.length > 0) {
            messageId = ($card.find('.card-header[message-id]').attr('message-id') || '').toString();
        }

        // Walk up to find a stable id in the DOM (headings often have ids for ToC).
        var idNode = el;
        while (idNode && idNode !== document.body && idNode !== ($card[0] || null)) {
            if (idNode.id) break;
            idNode = idNode.parentElement;
        }
        var anchorId = (idNode && idNode.id) ? idNode.id : '';

        // Capture the desired on-screen offset of the anchor (relative to chatView top).
        var desiredOffset = (el.getBoundingClientRect().top - rect.top);

        // Fallback: keep the same offset within the same message card.
        var cardOffset = null;
        if ($card.length > 0) {
            cardOffset = (el.getBoundingClientRect().top - $card[0].getBoundingClientRect().top);
        }

        return {
            anchorId: anchorId,
            messageId: messageId,
            desiredOffset: desiredOffset,
            cardOffset: cardOffset
        };
    } catch (e) {
        return null;
    }
}

function captureChatViewScrollAnchorForCard($chatView, $card) {
    /**
     * Capture a scroll anchor STRICTLY inside the given message card.
     * NEVER falls back to a generic (non-card-scoped) capture — that would anchor
     * to a different card and cause scroll jumps to the wrong position.
     *
     * If $card is not provided or not found, forces the last .message-card in chatView.
     *
     * Fallback chain (all card-scoped):
     * 1. elementFromPoint → find visible element with ID inside the card
     * 2. Card header message-id + offset from card top
     * 3. null (caller should skip restoration)
     *
     * @param {jQuery} $chatView
     * @param {jQuery} $card - The specific card to anchor to (forced to last card if null)
     * @returns {Object|null}
     */
    try {
        if (!$chatView || $chatView.length === 0 || !$chatView[0]) return null;
        var container = $chatView[0];
        var chatRect = container.getBoundingClientRect();
        if (!chatRect || chatRect.width <= 0 || chatRect.height <= 0) return null;

        // Force to last message card if no card provided or card not in DOM
        if (!$card || $card.length === 0 || !$card[0]) {
            $card = $chatView.find('.card.message-card').last();
        }
        if (!$card || $card.length === 0 || !$card[0]) return null;

        var cardEl = $card[0];
        var cardRect = cardEl.getBoundingClientRect();

        // Get message-id early — used as fallback anchor
        var messageId = '';
        try {
            messageId = ($card.find('.card-header[message-id]').attr('message-id') || '').toString();
        } catch (e) { messageId = ''; }

        // Compute intersection of card with chatView viewport.
        var yMin = Math.max(chatRect.top + 20, cardRect.top + 20);
        var yMax = Math.min(chatRect.bottom - 20, cardRect.bottom - 20);

        if (yMin < yMax) {
            // Card is visible — try elementFromPoint to find a specific element
            var x = chatRect.left + Math.min(80, chatRect.width * 0.5);
            var y = yMin + Math.min(120, (yMax - yMin) * 0.25);
            var el = document.elementFromPoint(x, y);

            if (el && container.contains(el) && cardEl.contains(el)) {
                // Found a visible element inside the card — walk up to find an ID
                var idNode = el;
                while (idNode && idNode !== document.body && idNode !== cardEl) {
                    if (idNode.id) break;
                    idNode = idNode.parentElement;
                }
                var anchorId = (idNode && idNode.id) ? idNode.id : '';
                var desiredOffset = (el.getBoundingClientRect().top - chatRect.top);
                var cardOffset = (el.getBoundingClientRect().top - cardRect.top);

                return {
                    anchorId: anchorId,
                    messageId: messageId,
                    desiredOffset: desiredOffset,
                    cardOffset: cardOffset
                };
            }
        }

        // Fallback: card-scoped anchor using the card's own position.
        // This handles cases where elementFromPoint misses (overlay, card partially visible, etc.)
        var fallbackOffset = Math.max(0, chatRect.top - cardRect.top);
        return {
            anchorId: '',
            messageId: messageId,
            desiredOffset: 0,
            cardOffset: fallbackOffset
        };
    } catch (e) {
        return null;
    }
}

function restoreChatViewScrollAnchor($chatView, anchor) {
    /**
     * Restore the chat view scroll position using a captured anchor.
     * This adjusts scrollTop by the delta required to keep the anchor at the same viewport offset.
     */
    try {
        if (!anchor || !$chatView || $chatView.length === 0 || !$chatView[0]) return false;
        var container = $chatView[0];
        var rect = container.getBoundingClientRect();
        if (!rect) return false;

        // 1) Prefer restoring by a stable element id.
        if (anchor.anchorId) {
            var target = document.getElementById(anchor.anchorId);
            if (target) {
                var newOffset = target.getBoundingClientRect().top - rect.top;
                var delta = newOffset - (anchor.desiredOffset || 0);
                if (isFinite(delta) && Math.abs(delta) > 0.5) {
                    var newTop = ($chatView.scrollTop() || 0) + delta;
                    var maxTop = ($chatView.prop('scrollHeight') || 0) - ($chatView.innerHeight() || 0);
                    if (isFinite(maxTop)) {
                        newTop = Math.max(0, Math.min(maxTop, newTop));
                    } else {
                        newTop = Math.max(0, newTop);
                    }
                    $chatView.scrollTop(newTop);
                }
                return true;
            }
        }

        // 2) Fallback: restore within the same message card by message-id.
        if (anchor.messageId && anchor.cardOffset !== null && anchor.cardOffset !== undefined) {
            var $header = $chatView.find('.message-card .card-header[message-id="' + anchor.messageId + '"]').first();
            if ($header.length > 0) {
                var $card = $header.closest('.card.message-card');
                if ($card.length > 0) {
                    var cardRect = $card[0].getBoundingClientRect();
                    var targetViewportY = cardRect.top + anchor.cardOffset;
                    var desiredViewportY = rect.top + (anchor.desiredOffset || 0);
                    var delta2 = targetViewportY - desiredViewportY;
                    if (isFinite(delta2) && Math.abs(delta2) > 0.5) {
                        var newTop2 = ($chatView.scrollTop() || 0) + delta2;
                        var maxTop2 = ($chatView.prop('scrollHeight') || 0) - ($chatView.innerHeight() || 0);
                        if (isFinite(maxTop2)) {
                            newTop2 = Math.max(0, Math.min(maxTop2, newTop2));
                        } else {
                            newTop2 = Math.max(0, newTop2);
                        }
                        $chatView.scrollTop(newTop2);
                    }
                    return true;
                }
            }
        }
    } catch (e) { /* ignore */ }
    return false;
}

function showMore(parentElem, text = null, textElem = null, as_html = false, show_at_start = false, server_side = null) {
    var _smT = _perfStart('showMore');
    if (textElem) {
        // For as_html=true with !show_at_start (the common lazy-collapse path),
        // we don't need text at all — defer .html()/.text() to avoid expensive
        // serialization on 76+ collapsed cards.
        // For as_html=false path, we still need text extraction.
        if (!as_html) {
            var text = textElem.text();
        }
        // as_html + show_at_start: text extracted below only when needed
    }
    else if ((text) || (typeof text === 'string')) {
        var textElem = $('<small class="summary-text"></small>');
    } else {
        throw "Either text or textElem must be provided to `showMore`"
    }

    if (as_html) {

        // --- LAZY COLLAPSE for cards that start hidden (show_at_start=false) ---
        // Skip ALL DOM reparenting. Instead, hide the textElem's content directly
        // and prepend a lightweight preview + [show] link. On first expand, the
        // delegated handler promotes to the full showMore structure.
        //
        // Optimised to use native DOM throughout — no jQuery element creation,
        // no jQuery .attr(), no jQuery .prepend(). This shaves ~12ms per call
        // (65 calls × 12ms = ~780ms savings on collapsed cards).
        if (!show_at_start) {
            var _rawEl = textElem[0];
            // Extract 10-char preview via native textContent (fast).
            var shortText = (_rawEl.textContent || '').slice(0, 10);

            // Mark as lazily collapsed — the delegated handler detects this.
            _rawEl.setAttribute('data-lazy-collapse', 'true');
            if (server_side && server_side.message_id) {
                _rawEl.setAttribute('data-showmore-message-id', server_side.message_id);
            }

            // Hide content with a single CSS class on the parent — the
            // `.lazy-collapsed > *` rule hides all children while
            // `.lazy-collapsed > .less-text, .lazy-collapsed > a.show-more`
            // keeps the preview + link visible.  O(1) classList.add replaces
            // the previous O(n_children) per-child style.display loop.
            _rawEl.classList.add('lazy-collapsed');
            // Prepend preview + [show] link using native DOM (avoids jQuery HTML parsing).
            var lessEl = document.createElement('span');
            lessEl.className = 'less-text';
            lessEl.style.display = 'block';
            lessEl.textContent = shortText;
            var smEl = document.createElement('a');
            smEl.href = '#';
            smEl.className = 'show-more';
            smEl.textContent = '[show]';
            // Insert at top: lessText first, then [show] link
            _rawEl.insertBefore(smEl, _rawEl.firstChild);
            _rawEl.insertBefore(lessEl, _rawEl.firstChild);

            _perfEnd('showMore', _smT);
            return null;
        }

        // --- R1 OPTIMISATION: in-place wrapAll instead of serialize→clone→destroy→rebuild ---
        // Previous code: textElem.html() → $('<span>').html(text) → textElem.empty() → rebuild
        //   Cost: 2 full HTML serialize/parse cycles per message (10-100KB each).
        // New code: wrap existing children in-place → O(1) DOM reparenting, zero serialization.

        // Remove any pre-existing showMore links inside textElem (prevents nested wrappers
        // if showMore is somehow called twice on the same element).
        // Use native querySelectorAll instead of jQuery .find().remove().
        var _existingLinks = textElem[0].querySelectorAll('.show-more');
        for (var _ri = 0; _ri < _existingLinks.length; _ri++) {
            _existingLinks[_ri].parentNode.removeChild(_existingLinks[_ri]);
        }

        // Compute 10-char preview from the live text content.
        // Use native textContent — jQuery .text() walks internal helpers and is 5-10x slower.
        var shortText = (textElem[0].textContent || '').slice(0, 10);
        var lessText = $('<span class="less-text" style="display:block;">' + shortText + '</span>');
        var smClick = $(' <a href="#" class="show-more">[show]</a> ');

        // HEIGHT LOCK: Prevent scroll shift during DOM reparenting.
        // Only needed when the card is in the live DOM (offsetHeight > 0).
        // For off-DOM cards (hybrid Phase 2 build), skip entirely — offsetHeight
        // returns 0 and the lock is pointless.
        var _smHeightLockEl = null;
        var _smHeightLockValue = 0;
        try {
            _smHeightLockEl = textElem.closest('.chat-card-body')[0] || textElem.parent()[0];
            if (_smHeightLockEl) {
                _smHeightLockValue = _smHeightLockEl.offsetHeight || 0;
                if (_smHeightLockValue > 0) {
                    _smHeightLockEl.style.minHeight = _smHeightLockValue + 'px';
                }
            }
        } catch (e) { /* ignore */ }

        // Wrap all existing children in-place into .more-text (hidden).
        // This is O(n_children) DOM reparenting — no serialization, no cloning.
        var $children = textElem.contents();
        if ($children.length) {
            $children.wrapAll('<span class="more-text" style="display:none;"></span>');
        } else {
            // Edge case: textElem is empty (shouldn't happen for >300 chars, but be safe)
            textElem.append('<span class="more-text" style="display:none;"></span>');
        }
        var moreText = textElem.find('.more-text').first();

        // Prepend preview text and [show] link BEFORE the .more-text wrapper.
        moreText.before(lessText).before(smClick);
        // Append a clone of [show] inside .more-text (appears as [hide] at bottom of expanded content).
        moreText.append(smClick.clone());

        // --- Tabs + ToC: eager for expanded, DEFERRED for collapsed messages ---
        // For show_at_start=true (expanded): run tabs+ToC now (same cost as before, but no
        //   serialize/parse overhead). These are needed immediately because content is visible.
        // For show_at_start=false (collapsed, the majority on history load): DEFER tabs+ToC
        //   to the first [show] click. The content is display:none, so the tab UI and ToC
        //   are invisible anyway. The delegated toggle handler at common.js:2507 already
        //   calls applyModelResponseTabs + updateMessageTocForElement on expand.
        //   Savings: ~15 messages x (tabs + ToC) deferred = 0.5-1s additional.
        if (show_at_start) {
            // Eager path: content will be visible immediately.
            try {
                if (typeof applyModelResponseTabs === 'function') {
                    applyModelResponseTabs(moreText);
                }
            } catch (e) { /* ignore */ }
            try {
                if (typeof updateMessageTocForElement === 'function') {
                    // Pass empty string for rawMarkdown — updateMessageTocForElement
                    // reads word count from the live DOM ($cardBody.text()) and only
                    // uses rawMarkdown as a fallback.  Calling moreText.html() here
                    // would serialize the entire card HTML (10-100KB), costing 5-50ms
                    // per expanded card, for a fallback path that never triggers.
                    updateMessageTocForElement(moreText, '', false);
                }
            } catch (e) { /* ignore */ }
        }
        // else: collapsed — tabs+ToC deferred to first expand (delegated handler covers it).

        // RELEASE HEIGHT LOCK.
        try {
            if (_smHeightLockEl && _smHeightLockValue > 0) {
                _smHeightLockEl.style.minHeight = '';
            }
        } catch (e) { /* ignore */ }
    }
    else {
        var moreText = text.slice(20);
        if (moreText) {
            var lessText = text.slice(0, 20);
            textElem.append(lessText + '<span class="more-text" style="display:none;">' + moreText + '</span>' + ' <a href="#" class="show-more">[show]</a>');
        } else {
            textElem.append(text);
        }
    }

    if (parentElem) {
        parentElem.append(textElem);
    }

    function toggle(event, api_call_trigger = true) {
        if (event) {
            event.preventDefault();
            event.stopPropagation();
        }
        var moreText = textElem.find('.more-text');
        var lessText = textElem.find('.less-text');
        if (moreText.is(':visible')) {
            moreText.hide();
            if (lessText) {
                lessText.show()
            }
            textElem.find('.show-more').each(function () { $(this).text('[show]'); })
            $(this).text('[show]');
        } else {
            moreText.show();
            if (lessText) {
                lessText.hide()
            }
            textElem.find('.show-more').each(function () { $(this).text('[hide]'); })
            $(this).text('[hide]');

            // Ensure model tabs (if any) are applied after expanding.
            try {
                if (typeof applyModelResponseTabs === 'function') {
                    applyModelResponseTabs(moreText);
                }
            } catch (e) { /* ignore */ }

            // After expanding, ensure ToC exists and is up to date for the expanded content.
            try {
                if (typeof updateMessageTocForElement === 'function') {
                    // Pass empty string — updateMessageTocForElement reads word count
                    // from the live DOM; moreText.html() would serialize 10-100KB for nothing.
                    updateMessageTocForElement(moreText, '', false);
                }
            } catch (e) { /* ignore */ }
        }

        // Sync TOC visibility with message collapse state
        try {
            var $tocCard = textElem.closest('.card.message-card');
            if ($tocCard.length) {
                var $tocContainer = $tocCard.find('.message-toc-container').first();
                if ($tocContainer.length) {
                    if (moreText.is(':visible')) {
                        $tocContainer.show();
                    } else {
                        $tocContainer.hide();
                    }
                }
            }
        } catch (e) { /* ignore */ }

        // if server_side is an object then call the server side flask api and save the state of whether we should show or hide the text
        if (server_side && typeof server_side === 'object' && api_call_trigger) {
            var show_hide = moreText.is(':visible') ? 'show' : 'hide';
            var message_id = server_side.message_id;
            var conversation_id = ConversationManager.activeConversationId;
            if (window.ConversationUIState) {
                window.ConversationUIState.updateMessage(conversation_id, message_id, show_hide);
            }
            
            // Make API call to save show/hide state
            apiCall(`/show_hide_message_from_conversation/${conversation_id}/${message_id}/0`, 'POST', {
                'show_hide': show_hide
            }).done(function(data) {
                // [DEBUG] console.log('Show/hide state saved: ' + show_hide);
            }).fail(function(xhr, status, error) {
                alert('Failed to save show/hide state: ' + (xhr.responseJSON?.message || error || 'Unknown error'));
            });
        }
    }

    if (show_at_start) {
        toggle(null, false);
    }


    textElem.find('.show-more').click(toggle);
    _perfEnd('showMore', _smT);
    return toggle;
}

function disableMainFunctionality() {
    // darken the screen
    $("body").append('<div id="overlay" style="position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0, 0, 0, 0.6); z-index: 999999;"><div class="spinner-border text-primary" role="status" style="position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%);"><span class="sr-only">Loading...</span></div></div>');

    // scroll to the OpenAI key input field
    $('html, body').animate({
        scrollTop: $("#openAIKey").offset().top
    }, 1000);
}

function enableMainFunctionality() {
    // remove the overlay and spinner
    $("#overlay").remove();

    // scroll back to the top of the page
    $('html, body').animate({
        scrollTop: 0
    }, 1000);
}

function initialiseVoteBank(cardElem, text, contentId = null, activeDocId = null, disable_voting = false) {
    // --- Inner helpers (closures over cardElem, text, etc.) ---

    // Copy: inline the logic directly — no ghost button needed.
    function handleCopyClick() {
        copyToClipboard(cardElem, text.replace('<answer>', '').replace('</answer>', '').trim());
    }

    // Edit: inline the logic directly — no ghost button needed.
    function handleEditClick() {
        // IMPORTANT: capture per-card identifiers as locals (avoid shared globals).
        // Otherwise, opening the editor for another card can overwrite these values and
        // cause the Save action to update the wrong message.
        const messageId = cardElem.find('.card-header').last().attr('message-id');
        const messageIndex = cardElem.find('.card-header').last().attr('message-index');
        const targetCardElem = cardElem;
        const conversationId = ConversationManager.activeConversationId;
        const fallbackText = text;

        // Open the editor with the supplied source text.
        function openEditorWith(sourceText) {
            // Use the new MarkdownEditorManager for enhanced editing experience
            if (typeof MarkdownEditorManager !== 'undefined') {
                MarkdownEditorManager.openEditor(sourceText, function(newtext) {
                    ConversationManager.saveMessageEditText(newtext, messageId, messageIndex, targetCardElem);
                });
            } else {
                // Fallback to original behavior if MarkdownEditorManager is not loaded
                $('#message-edit-text').val(sourceText);
                $('#message-edit-modal').modal('show');
                $('#message-edit-text-save-button').off();
                $('#message-edit-text-save-button').click(function () {
                    var newtext = $('#message-edit-text').val();
                    ConversationManager.saveMessageEditText(newtext, messageId, messageIndex, targetCardElem);
                    $('#message-edit-modal').modal('hide');
                });
            }
        }

        // Prefer the PERSISTED message text (single source of truth) over the live
        // card text. The live text accumulated during streaming includes display-only
        // blocks that the backend never saves (e.g. the "PKB Retrieval Details"
        // collapsible and <tool_calls_summary>); editing the live text would re-save
        // that junk. Fetching the stored text mirrors what a page reload shows.
        // Fall back to the live card text when the message isn't persisted yet
        // (e.g. temporary/stateless chats) or the fetch fails.
        if (conversationId && messageId && messageId !== 'undefined') {
            $.ajax({
                url: '/get_message_text/' + encodeURIComponent(conversationId) + '/' + encodeURIComponent(messageId),
                type: 'GET',
                dataType: 'json',
                success: function (resp) {
                    var storedText = (resp && typeof resp.text === 'string') ? resp.text : fallbackText;
                    openEditorWith(storedText);
                },
                error: function () {
                    // Not persisted (temp chat) or transient error — edit the live text.
                    openEditorWith(fallbackText);
                }
            });
        } else {
            openEditorWith(fallbackText);
        }
    }

    // --- Ghost buttons removed (Item 4 perf optimization) ---
    // The 4 TTS ghost buttons (ttsBtn, shortTtsBtn, podcastTtsBtn, shortPodcastTtsBtn)
    // were created with full styles/handlers but NEVER appended to the DOM in the
    // dropdown path. All dropdown items call handleTTSBtnClick() directly.
    // copyBtn and editBtn are replaced by handleCopyClick() and handleEditClick() above.

// ... existing code ...

    // We'll create a container for the audio or player
    function createAudioPlayer(audioUrl, autoPlay) {
        let audioContainer = $('<div>')
            .addClass('audio-container')
            .css({
                'display': 'flex',
                'align-items': 'center',
                'gap': '5px'
            });
        
        // If using streaming (autoPlay = true), the audioUrl is a MediaSource object URL
        // If not streaming, audioUrl is a full MP3 blob object URL

        let audioPlayer = $('<audio controls>')
            .addClass('tts-audio')
            .css({
                'height': '30px',
                'width': Math.min(window.innerWidth * 0.4, 400) + 'px'
            })
            .attr('src', audioUrl);

        // Autoplay if requested (HTML property)
        if (autoPlay) {
            audioPlayer.attr('autoplay', 'autoplay');
        }
        
        // Instead of an explicit "Loading..." item, you can add your own
        let loadingIndicator = $('<span>')
            .addClass('loading-indicator')
            .text('Loading...')
            .hide();

        // Refresh button
        let refreshBtn = $('<button>')
            .addClass('vote-btn')
            .addClass('refresh-tts-btn')
            .html('<i class="fas fa-sync-alt"></i>')
            .hide();
            
        // Close button to restore dropdown
        let closeBtn = $('<button>')
            .addClass('vote-btn')
            .addClass('close-tts-btn')
            .html('<i class="fas fa-times"></i>')
            .css({
                'margin-left': '5px',
                'color': '#dc3545'
            })
            .attr('title', 'Close Audio Player');

        // Refresh logic
        refreshBtn.click(() => {
            refreshBtn.hide();
            loadingIndicator.show();
            // Force recompute
            ConversationManager.convertToTTS(text, messageId, messageIndex, cardElem, true, autoPlay, shortTTS, podcastTTS)
                .then(newUrl => {
                    // Revoke old URL if needed
                    if (audioPlayer.attr('src')) {
                        URL.revokeObjectURL(audioPlayer.attr('src'));
                    }
                    audioPlayer.attr('src', newUrl);
                    loadingIndicator.hide();
                    refreshBtn.show();

                    if (autoPlay) {
                        audioPlayer[0].play().catch(e => console.log('Autoplay prevented:', e));
                    }
                })
                .catch(err => {
                    alert('Failed to refresh TTS: ' + err.message);
                    console.error(err);
                    loadingIndicator.hide();
                });
        });

        // Show refresh once the audio starts playing
        audioPlayer.on('play', () => {
            refreshBtn.show();
            loadingIndicator.hide();
        });

        // Close button logic
        closeBtn.click(() => {
            // Remove audio player container and restore dropdown
            let audioPlayerContainer = audioContainer.closest('.audio-player-container');
            let voteDropdown = audioPlayerContainer.prev('.dropdown');
            
            if (voteDropdown.length > 0) {
                voteDropdown.show();
                audioPlayerContainer.remove();
            } else {
                // Fallback: just remove the audio container
                audioContainer.remove();
            }
            
            // Revoke URL to free memory
            if (audioPlayer.attr('src')) {
                URL.revokeObjectURL(audioPlayer.attr('src'));
            }
        });

        audioContainer.append(loadingIndicator, audioPlayer, refreshBtn, closeBtn);
        return audioContainer;
    }

    // TTS click

    function handleTTSBtnClick(isShort, isPodcast = false) {
        const messageId = cardElem.find('.card-header').last().attr('message-id');
        const messageIndex = cardElem.find('.card-header').last().attr('message-index');
        
        // For demonstration: set autoPlay = true
        // If you want to decide this conditionally, you can do so based on user settings
        let autoPlay = true;  // We'll do streaming auto-play
        
        let audioContainer = createAudioPlayer('', autoPlay);
        

        // Find the vote dropdown and hide it, then show audio container
        let voteDropdown = cardElem.find('.vote-dropdown-menu').closest('.dropdown');
        let audioPlayerContainer = $('<div class="audio-player-container d-inline-block"></div>');
        audioPlayerContainer.append(audioContainer);
        
        if (voteDropdown.length > 0) {
            // Hide the dropdown and show audio player
            voteDropdown.hide();
            voteDropdown.after(audioPlayerContainer);
        } else {
            // Fallback for old button structure (no dropdown menu)
            // Replace the vote-box content with the audio player
            var $voteBox = cardElem.find('.vote-box');
            if ($voteBox.length) {
                $voteBox.empty().append(audioContainer);
            } else {
                cardElem.append(audioPlayerContainer);
            }
        }

        let loadingIndicator = audioContainer.find('.loading-indicator');
        let audioPlayer = audioContainer.find('audio');
        let refreshBtn = audioContainer.find('.refresh-tts-btn');

        loadingIndicator.show();
        audioPlayer.hide();
        

        shortTTS = isShort;
        podcastTTS = isPodcast;

        ConversationManager.convertToTTS(text, messageId, messageIndex, cardElem, false, autoPlay, shortTTS, podcastTTS)
            .then(audioUrl => {
                audioPlayer.attr('src', audioUrl);
                audioPlayer.show();
                loadingIndicator.hide();

                // Attempt immediate playback if autoPlay is set
                if (autoPlay) {
                    audioPlayer[0].play().catch(e => console.log('Autoplay prevented:', e));
                }
            })
            .catch(err => {
                loadingIndicator.text('Error generating audio');
                console.error('TTS Error:', err);
            });
    }

    // Handle copy button in header — calls handleCopyClick() directly (no ghost button)
    let headerCopyBtn = cardElem.find('.copy-btn-header');
    if (headerCopyBtn.length > 0) {
        headerCopyBtn.click(function(e) {
            e.preventDefault();
            e.stopPropagation();
            handleCopyClick();
        });
    }
    
    // Find the dropdown menu in the card header
    let voteDropdown = cardElem.find('.vote-dropdown-menu');
    
    if (voteDropdown.length > 0) {
        // Perf (Item 1): Lazy-populate the dropdown on first open instead of eagerly
        // building 12 items + handlers for every card. Building ~12 elements is <1ms,
        // imperceptible to the user. Uses Bootstrap 4's show.bs.dropdown event via .one()
        // so it only runs once per card.
        var $dropdownParent = voteDropdown.closest('.dropdown');
        
        // On re-init (e.g. after message edit/revert), clear existing items so the
        // lazy builder repopulates with fresh text/state.
        voteDropdown.empty();
        // Remove any previously registered show.bs.dropdown handler to avoid duplication
        if ($dropdownParent.length) {
            $dropdownParent.off('show.bs.dropdown.lazyVoteBank');
        }
        
        // The population function — runs once on first dropdown open.
        function populateVoteDropdown() {
            // Guard: if already populated by a race, skip
            if (voteDropdown.children().length > 0) return;
            
            // Clear existing content
            voteDropdown.empty();
        
        // Word count info item
        var wordCount = text ? text.trim().split(/\s+/).filter(Boolean).length : 0;
        var wcItem = $('<span class="dropdown-item-text text-muted" style="font-size:0.7rem;padding:2px 12px;">' + wordCount.toLocaleString() + ' words</span>');
        voteDropdown.append(wcItem);
        
        // Add TTS buttons as dropdown items
        let shortTtsItem = $('<a class="dropdown-item" href="#"><i class="bi bi-volume-up mr-2"></i>Short TTS</a>');
        let ttsItem = $('<a class="dropdown-item" href="#"><i class="bi bi-music-note mr-2"></i>Full TTS</a>');
        let shortPodcastItem = $('<a class="dropdown-item" href="#"><i class="bi bi-broadcast mr-2"></i>Short Podcast</a>');
        let podcastItem = $('<a class="dropdown-item" href="#"><i class="bi bi-broadcast-pin mr-2"></i>Full Podcast</a>');
        let editItem = $('<a class="dropdown-item" href="#"><i class="bi bi-pencil mr-2"></i>Edit Message</a>');
        let editAsArtefactItem = $('<a class="dropdown-item" href="#"><i class="bi bi-files mr-2"></i>Edit as Artefact</a>');
        
        // Add click handlers
        shortTtsItem.click(function(e) {
            e.preventDefault();
            handleTTSBtnClick(true);
        });
        
        ttsItem.click(function(e) {
            e.preventDefault();
            handleTTSBtnClick(false);
        });
        
        shortPodcastItem.click(function(e) {
            e.preventDefault();
            handleTTSBtnClick(true, true);
        });
        
        podcastItem.click(function(e) {
            e.preventDefault();
            handleTTSBtnClick(false, true);
        });
        
        editItem.click(function(e) {
            e.preventDefault();
            handleEditClick();
        });

        editAsArtefactItem.click(function(e) {
            e.preventDefault();
            if (disable_voting) {
                showToast('Edit as Artefact is only available for assistant messages', 'warning');
                return;
            }
            const messageId = cardElem.find('.card-header').last().attr('message-id');
            const messageIndex = cardElem.find('.card-header').last().attr('message-index');
            if (!messageId || messageId === 'undefined') {
                showToast('Message is still loading. Try again once the response finishes.', 'warning');
                return;
            }
            if (typeof ArtefactsManager === 'undefined' || !ArtefactsManager.openModalForMessage) {
                showToast('Artefacts manager is not available', 'error');
                return;
            }
            ArtefactsManager.openModalForMessage(
                ConversationManager.activeConversationId,
                messageId,
                messageIndex,
                cardElem,
                text
            );
        });
        
        // Add items to dropdown
        voteDropdown.append(shortTtsItem, ttsItem);
        
        // Add podcast items for wider screens
        if (window.innerWidth > 768) {
            voteDropdown.append(shortPodcastItem, podcastItem);
        }
        
        // Add Table of Contents menu item
        var tocItem = $('<a class="dropdown-item floating-toc-trigger" href="#"><i class="bi bi-list-ul mr-2"></i>Table of Contents</a>');
        tocItem.click(function(e) {
            e.preventDefault();
            e.stopPropagation();
            // Close the dropdown menu before showing floating ToC
            try {
                var $dropdown = $(this).closest('.dropdown');
                if ($dropdown.length > 0) {
                    // Bootstrap 4.6 dropdown hide
                    $dropdown.find('[data-toggle="dropdown"]').dropdown('hide');
                }
            } catch (err) { /* ignore */ }
            showFloatingToc(cardElem);
        });
        
        voteDropdown.append($('<div class="dropdown-divider"></div>'), tocItem);
        
        // Save to Memory - runs extraction pipeline on message text
        var saveToMemoryItem = $('<a class="dropdown-item" href="#"><i class="bi bi-journal-plus mr-2"></i>Save to Memory</a>');
        saveToMemoryItem.click(function(e) {
            e.preventDefault();
            e.stopPropagation();
            // Close the dropdown first
            try {
                var $dropdown = $(this).closest('.dropdown');
                if ($dropdown.length > 0) {
                    $dropdown.find('[data-toggle="dropdown"]').dropdown('hide');
                }
            } catch (err) { /* ignore */ }
            if (typeof PKBManager !== 'undefined' && PKBManager.proposeFromText) {
                PKBManager.proposeFromText(text);
            } else if (typeof PKBManager !== 'undefined' && PKBManager.openAddClaimModalWithText) {
                PKBManager.openAddClaimModalWithText(text);
            } else {
                console.warn('PKBManager not available for Save to Memory');
            }
        });
        
        voteDropdown.append($('<div class="dropdown-divider"></div>'), editItem, editAsArtefactItem, saveToMemoryItem);

        // "Compare with…" item — only for assistant messages
        if (!disable_voting) {
            var compareItem = $('<a class="dropdown-item" href="#"><i class="bi bi-arrow-left-right mr-2"></i>Compare with\u2026</a>');
            compareItem.click(function(e) {
                e.preventDefault();
                e.stopPropagation();
                try {
                    var $dropdown = $(this).closest('.dropdown');
                    if ($dropdown.length > 0) $dropdown.find('[data-toggle="dropdown"]').dropdown('hide');
                } catch (err) { /* ignore */ }
                var messageId = cardElem.find('.card-header').last().attr('message-id');
                if (!messageId || messageId === 'undefined') {
                    showToast('Message is still loading. Try again once the response finishes.', 'warning');
                    return;
                }
                if (typeof CompareManager === 'undefined') {
                    showToast('Compare manager is not available', 'error');
                    return;
                }
                // Fetch persisted text to avoid stale closure after edits
                var convId = ConversationManager.activeConversationId;
                $.get('/get_message_text/' + convId + '/' + messageId, function(data) {
                    CompareManager.open(convId, messageId, data.text || text);
                }).fail(function() {
                    CompareManager.open(convId, messageId, text);
                });
            });
            voteDropdown.append($('<div class="dropdown-divider"></div>'), compareItem);
        }

        // "Undo Last Edit" — only for assistant messages; hidden until a prior version exists.
        // Each click reverts one edit at a time (walks back through the edit stack).
        if (!disable_voting) {
            var revertItem = $('<a class="dropdown-item revert-to-original-btn" href="#" style="display:none"><i class="bi bi-arrow-counterclockwise mr-2"></i>Undo Last Edit</a>');
            revertItem.click(function(e) {
                e.preventDefault();
                e.stopPropagation();
                try {
                    var $dropdown = $(this).closest('.dropdown');
                    if ($dropdown.length > 0) $dropdown.find('[data-toggle="dropdown"]').dropdown('hide');
                } catch (err) { /* ignore */ }
                var revertMsgId = cardElem.find('.card-header').last().attr('message-id');
                var revertMsgIdx = cardElem.find('.card-header').last().attr('message-index') || '0';
                var revertConvId = ConversationManager.activeConversationId;
                if (!revertMsgId || revertMsgId === 'undefined') {
                    showToast('Cannot revert: message ID not available', 'warning');
                    return;
                }
                if (!confirm('Undo the most recent edit to this answer? You can keep undoing earlier edits one at a time.')) return;
                $.ajax({
                    url: '/revert_message_from_conversation/' + encodeURIComponent(revertConvId) + '/' + encodeURIComponent(revertMsgId) + '/' + revertMsgIdx,
                    method: 'POST',
                    contentType: 'application/json',
                    success: function(resp) {
                        var remaining = (resp && typeof resp.versions_remaining === 'number') ? resp.versions_remaining : 0;
                        showToast(remaining > 0 ? 'Reverted one edit (' + remaining + ' earlier version' + (remaining === 1 ? '' : 's') + ' left)' : 'Reverted to original answer', 'success');
                        var restoredText = resp.text || '';
                        // Mark/clear the header flag so the re-init'd revert item reflects
                        // whether further undo steps remain.
                        var $hdr = cardElem.find('.card-header').last();
                        if (remaining > 0) {
                            $hdr.attr('data-has-original', 'true');
                        } else {
                            $hdr.removeAttr('data-has-original');
                        }
                        if (restoredText) {
                            var $body = cardElem.find('.actual-card-text').last();
                            if ($body.length && typeof renderInnerContentAsMarkdown === 'function') {
                                renderInnerContentAsMarkdown($body, function() {}, false, restoredText);
                            } else if ($body.length) {
                                $body.text(restoredText);
                            }
                            // Re-init vote bank with restored text. The new revert item
                            // shows immediately when versions remain (data-has-original).
                            initialiseVoteBank(cardElem, restoredText, contentId, activeDocId, disable_voting);
                        }
                        // Hide this (old) item; the re-init created a fresh one.
                        if (remaining <= 0) revertItem.hide();
                        // Invalidate the cached rendered-HTML snapshot so a reload
                        // shows the reverted text rather than stale cached markup.
                        try {
                            if (window.RenderedStateManager && window.RenderedStateManager.invalidate) {
                                window.RenderedStateManager.invalidate(revertConvId);
                            }
                        } catch (_e) { /* best-effort */ }
                    },
                    error: function(xhr) {
                        var errMsg = (xhr.responseJSON && xhr.responseJSON.error) || 'Failed to revert';
                        showToast(errMsg, 'error');
                    }
                });
            });
            voteDropdown.append(revertItem);

            // Lazily check whether a prior version exists — fires during the
            // first dropdown open (which is now also the population event).
            // No need for a separate click.revertcheck handler since the dropdown
            // is lazy-populated on first show.bs.dropdown.
            (function(item, card) {
                var $hdr = card.find('.card-header').last();
                // Fast path: flag set right after an in-session edit or partial revert.
                if ($hdr.attr('data-has-original') === 'true') {
                    item.show();
                    return;
                }
                // Fire the check immediately (we're inside the first dropdown open)
                var cId = ConversationManager.activeConversationId;
                var mId = card.find('.card-header').last().attr('message-id');
                if (!cId || !mId || mId === 'undefined') return;
                $.get('/get_message_text/' + encodeURIComponent(cId) + '/' + encodeURIComponent(mId), function(resp) {
                    if (resp && resp.original_text !== null && resp.original_text !== undefined) {
                        item.show();
                    }
                }).fail(function() { /* no-op */ });
            })(revertItem, cardElem);
        }

        // "Read Full Screen" — open the reading overlay for this message (all cards, user and assistant)
        var readFullScreenItem = $('<a class="dropdown-item reading-overlay-trigger" href="#"><i class="bi bi-arrows-fullscreen mr-2"></i>Read Full Screen</a>');
        readFullScreenItem.click(function(e) {
            e.preventDefault();
            e.stopPropagation();
            try {
                var $dropdown = $(this).closest('.dropdown');
                if ($dropdown.length > 0) $dropdown.find('[data-toggle="dropdown"]').dropdown('hide');
            } catch (err) { /* ignore */ }
            if (typeof window.openReadingOverlay === 'function') {
                window.openReadingOverlay(cardElem);
            }
        });
        voteDropdown.append($('<div class="dropdown-divider"></div>'), readFullScreenItem);
        } // end populateVoteDropdown()

        // Register the lazy builder: populate on first dropdown open.
        // Bootstrap 4.6 fires 'show.bs.dropdown' on the .dropdown parent.
        // .one() with namespace ensures it only runs once and can be cleaned up on re-init.
        if ($dropdownParent.length > 0) {
            $dropdownParent.one('show.bs.dropdown.lazyVoteBank', function() {
                populateVoteDropdown();
            });
        } else {
            // No dropdown parent found (shouldn't happen) — populate eagerly as fallback
            populateVoteDropdown();
        }
        
    } else {
        // Fallback to old vote box if dropdown not found (legacy layout)
        // Ghost buttons removed — create minimal inline buttons here instead.
        let voteBox = $('<div>')
            .addClass('vote-box')
            .css({ 'position': 'absolute', 'top': '5px', 'right': '30px' });

        let fbCopyBtn = $('<button>').addClass('vote-btn copy-btn').text('📋');
        fbCopyBtn.click(function() { handleCopyClick(); });
        let fbEditBtn = $('<button>').addClass('vote-btn edit-btn').text('✏️');
        fbEditBtn.click(function() { handleEditClick(); });
        let fbTtsBtn = $('<button>').addClass('vote-btn tts-btn').html('🔊');
        fbTtsBtn.click(function() { handleTTSBtnClick(false); });
        let fbShortTtsBtn = $('<button>').addClass('vote-btn short-tts-btn').html('🔉 S');
        fbShortTtsBtn.click(function() { handleTTSBtnClick(true); });

        voteBox.append(fbShortTtsBtn, fbTtsBtn, fbEditBtn, fbCopyBtn);
        cardElem.find('.vote-box').remove();
        cardElem.append(voteBox);
    }

    return;
}

/**
 * Find the nearest scrollable ancestor container for a jQuery element.
 * Prefers known chat containers; falls back to CSS overflow detection.
 * Hoisted from addScrollToTopButton — pure utility, no outer dependencies.
 * @param {jQuery} $elem
 * @returns {jQuery|null}
 */
function getScrollableAncestor($elem) {
    var preferredContainers = $('#doubt-chat-messages, #temp-llm-messages, #chatView');
    for (var i = 0; i < preferredContainers.length; i++) {
        var $container = $(preferredContainers[i]);
        if ($container.length > 0 && $container.find($elem).length > 0) {
            return $container;
        }
    }
    var $parents = $elem.parents();
    for (var j = 0; j < $parents.length; j++) {
        var $parent = $($parents[j]);
        var overflowY = ($parent.css('overflow-y') || '').toLowerCase();
        var overflow = ($parent.css('overflow') || '').toLowerCase();
        var isScrollable = (overflowY === 'auto' || overflowY === 'scroll' || overflow === 'auto' || overflow === 'scroll');
        if (isScrollable && $parent[0] && $parent[0].scrollHeight > $parent[0].clientHeight) {
            return $parent;
        }
    }
    return null;
}

/**
 * Scroll a container so the target element aligns to the top of the container viewport.
 * Hoisted from addScrollToTopButton — pure geometry utility, no outer dependencies.
 * @param {jQuery} $container
 * @param {jQuery} $target
 * @returns {boolean} True if a scroll was initiated.
 */
function scrollContainerToTargetTop($container, $target) {
    if (!$container || !$container.length || !$target || !$target.length) return false;
    var containerEl = $container[0];
    var targetEl = $target[0];
    if (!containerEl || !targetEl) return false;
    var containerRect = containerEl.getBoundingClientRect();
    var targetRect = targetEl.getBoundingClientRect();
    var delta = targetRect.top - containerRect.top;
    var targetScrollTop = $container.scrollTop() + delta;
    if (!isFinite(targetScrollTop)) return false;
    $container.animate({ scrollTop: targetScrollTop }, 300, 'swing');
    return true;
}

/**
 * Add a scroll-to-top button to a card element
 * @param {jQuery} cardElem - The card element to add the button to
 * @param {string} buttonText - Text for the button (default: "↑ Top")
 * @param {string} buttonClass - Additional CSS classes for the button
 */
window.addScrollToTopButton = function(cardElem, buttonText, buttonClass) {
    // R-H5b: Rewritten with native DOM — avoids jQuery $('<button>'), .css({10 props}),
    // .hover(), .click(), redundant .find() verification.  Styles now in CSS class.
    var el = (cardElem && cardElem.jquery) ? cardElem[0] : cardElem;
    if (!el) return null;

    // Deduplicate — check if button already exists
    if (el.querySelector('.scroll-to-top-btn')) {
        return el.querySelector('.scroll-to-top-btn');
    }

    var btn = document.createElement('button');
    btn.className = 'btn btn-sm scroll-to-top-btn ' + (buttonClass || '');
    btn.innerHTML = buttonText || '\u2191 Top';

    // Click handler — scroll card into view
    btn.addEventListener('click', function(e) {
        e.preventDefault();
        e.stopPropagation();
        var $ce = $(el);
        var $scrollableParent = getScrollableAncestor($ce);
        if ($scrollableParent && scrollContainerToTargetTop($scrollableParent, $ce)) {
            return;
        }
        var cardTop = $ce.offset().top;
        if (isFinite(cardTop)) {
            $('html, body').animate({ scrollTop: cardTop - 20 }, 300, 'swing');
        }
    });

    // Ensure relative positioning for absolute button (native — no getComputedStyle forced reflow)
    var pos = el.style.position;
    if (!pos || pos === 'static') {
        el.style.position = 'relative';
    }

    el.appendChild(btn);
    return btn;
};

// ============================================
// Delegated event handlers for snapshot-restored DOM
// ============================================
// When RenderedStateManager restores cached HTML, direct .click() bindings are lost.
// These delegated handlers ensure buttons work regardless of how DOM was populated.

// Delegated handler for scroll-to-top buttons
$(document).on('click', '.scroll-to-top-btn', function(e) {
    // Only handle if no direct handler is bound (avoid double-fire)
    // Direct handlers call e.stopPropagation(), so if we reach document, it's from snapshot restore
    e.preventDefault();
    var $btn = $(this);
    var $card = $btn.closest('.card.message-card');
    if (!$card.length) return;
    
    // Find scrollable ancestor
    var preferredContainers = $('#doubt-chat-messages, #temp-llm-messages, #chatView');
    var $scrollable = null;
    for (var i = 0; i < preferredContainers.length; i++) {
        var $container = $(preferredContainers[i]);
        if ($container.length > 0 && $container.find($card).length > 0) {
            $scrollable = $container;
            break;
        }
    }
    if (!$scrollable) {
        var $parents = $card.parents();
        for (var j = 0; j < $parents.length; j++) {
            var $p = $($parents[j]);
            var ov = ($p.css('overflow-y') || '').toLowerCase();
            if ((ov === 'auto' || ov === 'scroll') && $p[0].scrollHeight > $p[0].clientHeight) {
                $scrollable = $p;
                break;
            }
        }
    }
    if ($scrollable && $scrollable.length) {
        var containerRect = $scrollable[0].getBoundingClientRect();
        var targetRect = $card[0].getBoundingClientRect();
        var delta = targetRect.top - containerRect.top;
        var targetScrollTop = $scrollable.scrollTop() + delta;
        if (isFinite(targetScrollTop)) {
            $scrollable.animate({ scrollTop: targetScrollTop }, 300, 'swing');
            return;
        }
    }
    // Fallback: scroll window
    var cardTop = $card.offset().top;
    if (isFinite(cardTop)) {
        $('html, body').animate({ scrollTop: cardTop - 20 }, 300, 'swing');
    }
});

/**
 * Resolve the nearest scrollable container for a card. Mirrors the logic used by
 * the scroll-to-top button so the Top/Bottom controls behave identically across
 * the main chat view, the doubt modal and the temp-LLM modal.
 * @param {jQuery} $card
 * @returns {jQuery|null}
 */
window.getCardScrollableContainer = function($card) {
    var preferredContainers = $('#doubt-chat-messages, #temp-llm-messages, #chatView');
    for (var i = 0; i < preferredContainers.length; i++) {
        var $container = $(preferredContainers[i]);
        if ($container.length > 0 && $container.find($card).length > 0) {
            return $container;
        }
    }
    var $parents = $card.parents();
    for (var j = 0; j < $parents.length; j++) {
        var $p = $($parents[j]);
        var ov = ($p.css('overflow-y') || '').toLowerCase();
        if ((ov === 'auto' || ov === 'scroll') && $p[0] && $p[0].scrollHeight > $p[0].clientHeight) {
            return $p;
        }
    }
    return null;
};

/**
 * Create a "Bottom of answer" button (text + down arrow) that lives in a card
 * header's right-hand control group. Behaviour is provided by the delegated
 * `.scroll-to-bottom-btn` handler below, so this only builds the element.
 *
 * @param {string} buttonText  - label (default "Bottom" + a down arrow)
 * @param {string} buttonClass - extra css classes
 * @returns {jQuery} the button element
 */
window.makeScrollToBottomButton = function(buttonText, buttonClass) {
    return $('<button type="button">')
        .addClass('btn btn-sm p-1 scroll-to-bottom-btn ' + (buttonClass || ''))
        .attr('title', 'Jump to the bottom of this message')
        .html(buttonText || 'Bottom <i class="bi bi-arrow-down-short"></i>');
};

/**
 * Idempotently inject a Bottom button into a card's header right-side control
 * group (the `.d-flex.align-items-center` that holds copy/vote). Used to add the
 * control to freshly-streamed cards. Returns the button (existing or new).
 *
 * @param {jQuery} cardElem
 * @param {string} buttonText
 * @param {string} buttonClass
 */
window.addScrollToBottomButton = function(cardElem, buttonText, buttonClass) {
    var $card = (cardElem && cardElem.jquery) ? cardElem : $(cardElem);
    if (!$card || !$card.length) return null;
    var $existing = $card.find('> .card-header .scroll-to-bottom-btn').first();
    if ($existing.length) return $existing;
    var $headerRight = $card.find('> .card-header > .d-flex.align-items-center').last();
    if (!$headerRight.length) $headerRight = $card.find('> .card-header').first();
    if (!$headerRight.length) return null;
    var $btn = window.makeScrollToBottomButton(buttonText, buttonClass);
    $headerRight.prepend($btn);
    return $btn;
};

// Delegated handler for scroll-to-bottom buttons (Top button's counterpart).
// Scrolls the card's BOTTOM edge into view within its scrollable container.
$(document).on('click', '.scroll-to-bottom-btn', function(e) {
    e.preventDefault();
    e.stopPropagation();
    var $btn = $(this);
    var $card = $btn.closest('.card');
    if (!$card.length) return;

    var $container = window.getCardScrollableContainer($card);
    if ($container && $container.length) {
        var containerEl = $container[0];
        var cardEl = $card[0];
        var containerRect = containerEl.getBoundingClientRect();
        var cardRect = cardEl.getBoundingClientRect();
        // Align the card's bottom to the container's bottom.
        var delta = cardRect.bottom - containerRect.bottom;
        var targetScrollTop = $container.scrollTop() + delta;
        if (isFinite(targetScrollTop)) {
            $container.animate({ scrollTop: targetScrollTop }, 300, 'swing');
            return;
        }
    }
    // Fallback: scroll the window so the card bottom sits near the viewport bottom.
    var cardBottom = $card.offset().top + $card.outerHeight();
    var target = cardBottom - ($(window).height() - 20);
    if (isFinite(target)) {
        $('html, body').animate({ scrollTop: Math.max(0, target) }, 300, 'swing');
    }
});

// Delegated handler for the non-tabbed header hide toggle. Rather than introduce
// a competing collapse mechanism, it PROXIES the in-body showMore [show]/[hide]
// link, so collapse state and its server-side persistence stay unified with the
// existing per-message show/hide. (Tabbed answers keep their own nav toggle.)
$(document).on('click', '.header-hide-toggle', function(e) {
    e.preventDefault();
    e.stopPropagation();
    var $toggle = $(this);
    var $card = $toggle.closest('.card');
    if (!$card.length) return;
    var $sm = $card.find('.actual-card-text .show-more').first();
    if (!$sm.length) $sm = $card.find('.show-more').first();
    if ($sm.length) { $sm.trigger('click'); }
    // Sync this toggle's label to the resulting collapse state.
    setTimeout(function() {
        var $more = $card.find('.actual-card-text .more-text').first();
        if (!$more.length) $more = $card.find('.more-text').first();
        var collapsed = $more.length ? !$more.is(':visible') : false;
        $toggle.text(collapsed ? '[show]' : '[hide]');
    }, 0);
});

/**
 * Reveal + wire the header navigation controls (Bottom button, and for non-tabbed
 * answers a header [hide] toggle) on a rendered message card, and add the Top
 * button. Idempotent and safe to call from both the history-render and the
 * streaming-completion paths. The Top/Bottom buttons appear on BOTH user and
 * assistant cards once content is long enough.
 *
 * @param {jQuery} cardElem - the .message-card
 * @param {string} showHide - persisted 'show'/'hide' state for the answer
 */
window.decorateMessageCardNav = function(cardElem, showHide) {
    // R-H5b: Rewritten with native DOM — replaces 7 jQuery .find() calls per card
    // with native querySelector (2-5x faster per call, no jQuery overhead).
    var el = (cardElem && cardElem.jquery) ? cardElem[0] : cardElem;
    if (!el) return;

    // Bottom button (header, top-right) — reveal for any card that is long enough.
    var bottomBtn = el.querySelector(':scope > .card-header .scroll-to-bottom-btn');
    if (bottomBtn) { bottomBtn.style.display = ''; }

    // Top button (absolute, bottom-right) — add if not present.
    if (!el.querySelector('.scroll-to-top-btn') && typeof window.addScrollToTopButton === 'function') {
        window.addScrollToTopButton(el, 'Top \u2191', 'chat-scroll-top');
    }

    // Header hide toggle — only for NON-tabbed answers that have a showMore control.
    var isTabbed = !!el.querySelector('.chat-card-body[data-has-tabs]');
    var hasShowMore = !!el.querySelector('.actual-card-text .show-more, .show-more');
    var hideToggle = el.querySelector(':scope > .card-header .header-hide-toggle');
    if (hideToggle) {
        if (isTabbed || !hasShowMore) {
            hideToggle.style.display = 'none';
        } else {
            var collapsed = (showHide === 'hide');
            hideToggle.textContent = collapsed ? '[show]' : '[hide]';
            hideToggle.style.display = '';
        }
    }

    // Sync TOC visibility with the initial persisted collapse state.
    try {
        var tocContainer = el.querySelector('.message-toc-container');
        if (tocContainer) {
            var _decCompact = document.body.classList.contains('compact-nav');
            if (showHide === 'hide') {
                tocContainer.style.display = 'none';
            } else if (_decCompact && tocContainer.children.length > 0) {
                _tocCollapseForCompact($(tocContainer));
            } else if (tocContainer.children.length > 0) {
                tocContainer.style.display = '';
            }
        }
    } catch (e) { /* ignore */ }
};

// Delegated handler for show-more toggle links
$(document).on('click', '.show-more', function(e) {
    e.preventDefault();
    e.stopPropagation();
    var $link = $(this);
    // Find the parent text element that contains .more-text and .less-text
    var $textElem = $link.closest('.actual-card-text, .summary-text, [id]').first();
    if (!$textElem.length) {
        $textElem = $link.parent();
    }

    // --- LAZY COLLAPSE PROMOTION ---
    // If this card was lazily collapsed (no wrapAll during render), promote it
    // to the full showMore structure on first expand.
    if ($textElem.attr('data-lazy-collapse') === 'true') {
        $textElem.removeAttr('data-lazy-collapse');

        // Remove the CSS-driven collapse class — all children become visible.
        $textElem[0].classList.remove('lazy-collapsed');

        // Select the content children (everything except the preview + link)
        // for wrapping into .more-text.
        var $hiddenChildren = $textElem.children().not('.less-text').not('a.show-more');

        // Now wrap them into .more-text for toggle consistency going forward.
        // This wrapAll is a one-time cost on first expand only.
        $hiddenChildren.wrapAll('<span class="more-text"></span>');
        var $moreText = $textElem.find('.more-text').first();
        // Add [hide] link at the bottom
        $moreText.append(' <a href="#" class="show-more">[hide]</a> ');

        // Hide preview, update link text
        var $lessText = $textElem.find('.less-text');
        if ($lessText.length) $lessText.hide();
        $link.text('[hide]');

        // Apply deferred work: tabs + ToC
        try {
            if (typeof applyModelResponseTabs === 'function') {
                applyModelResponseTabs($moreText);
            }
        } catch (e2) { /* ignore */ }
        try {
            if (typeof updateMessageTocForElement === 'function') {
                // Pass empty string — ToC builds from DOM headings, not rawMarkdown.
                updateMessageTocForElement($moreText, '', false);
            }
        } catch (e2) { /* ignore */ }

        // Sync TOC visibility
        try {
            var $tocCard = $link.closest('.card.message-card');
            if ($tocCard.length) {
                $tocCard.find('.message-toc-container').first().show();
            }
        } catch (e2) { /* ignore */ }

        // R-H5a: Apply deferred nav decoration (scroll buttons, header-hide toggle,
        // ToC visibility). Skipped during initial render for collapsed cards.
        try {
            if (typeof window.decorateMessageCardNav === 'function') {
                var $navCard = $link.closest('.card.message-card');
                if ($navCard.length) {
                    window.decorateMessageCardNav($navCard, 'show');
                }
            }
        } catch (e2) { /* ignore */ }

        // Persist state
        try {
            var $card = $link.closest('.card.message-card');
            var messageId = $textElem.attr('data-showmore-message-id') || $card.find('.card-header[message-id]').attr('message-id');
            if (messageId && typeof ConversationManager !== 'undefined' && ConversationManager) {
                var convId = ConversationManager.activeConversationId;
                if (convId) {
                    if (window.ConversationUIState) {
                        window.ConversationUIState.updateMessage(convId, messageId, 'show');
                    }
                    apiCall('/show_hide_message_from_conversation/' + convId + '/' + messageId + '/0', 'POST', {
                        'show_hide': 'show'
                    });
                }
            }
        } catch (e2) { /* ignore */ }
        return;
    }

    var $moreText = $textElem.find('.more-text');
    var $lessText = $textElem.find('.less-text');
    
    if ($moreText.is(':visible')) {
        $moreText.hide();
        if ($lessText.length) $lessText.show();
        $textElem.find('.show-more').each(function() { $(this).text('[show]'); });
        // Sync TOC visibility — hide when message collapses
        try {
            var $tocCard = $link.closest('.card.message-card');
            if ($tocCard.length) {
                $tocCard.find('.message-toc-container').first().hide();
            }
        } catch (e) { /* ignore */ }
    } else {
        $moreText.show();
        if ($lessText.length) $lessText.hide();
        $textElem.find('.show-more').each(function() { $(this).text('[hide]'); });
        // Re-apply model tabs after expanding
        try {
            if (typeof applyModelResponseTabs === 'function') {
                applyModelResponseTabs($moreText);
            }
        } catch (e) { /* ignore */ }
        // Update ToC after expanding (renderMessageToc will show but only if moreText visible)
        try {
            if (typeof updateMessageTocForElement === 'function') {
                // Pass empty string — ToC builds from DOM headings, not rawMarkdown.
                updateMessageTocForElement($moreText, '', false);
            }
        } catch (e) { /* ignore */ }
        // R-H5a: Apply deferred nav decoration on expand (scroll buttons,
        // header-hide toggle).  Skipped during initial render for collapsed cards.
        try {
            if (typeof window.decorateMessageCardNav === 'function') {
                var $navCard = $link.closest('.card.message-card');
                if ($navCard.length) {
                    window.decorateMessageCardNav($navCard, 'show');
                }
            }
        } catch (e) { /* ignore */ }
    }
    
    // Persist show/hide state to server
    try {
        var $card = $link.closest('.card.message-card');
        var messageId = $card.find('.card-header[message-id]').attr('message-id');
        if (messageId && typeof ConversationManager !== 'undefined' && ConversationManager) {
            var convId = ConversationManager.activeConversationId;
            if (convId) {
                var showHide = $moreText.is(':visible') ? 'show' : 'hide';
                if (window.ConversationUIState) {
                    window.ConversationUIState.updateMessage(convId, messageId, showHide);
                }
                apiCall('/show_hide_message_from_conversation/' + convId + '/' + messageId + '/0', 'POST', {
                    'show_hide': showHide
                }).done(function() {
                    // [DEBUG] console.log('Show/hide state saved: ' + showHide);
                }).fail(function(xhr, status, error) {
                    console.error('Failed to save show/hide state:', error);
                });
            }
        }
    } catch (e) { /* ignore */ }
});

// Re-stamps message-index on every remaining card after an in-place DOM removal.
// This keeps fork, pair-delete, TTS, and edit from using stale positional indices.
function reindexMessageCards() {
    $('#chatView .card.message-card').each(function(i) {
        $(this).find('[message-index]').attr('message-index', i);
    });
}

// Delegated handler for delete-message-button (survives snapshot restore)
$(document).on('click', '.delete-message-button', function(e) {
    e.preventDefault();
    e.stopPropagation();
    var messageId = $(this).attr('message-id');
    var messageIndex = $(this).attr('message-index');
    var conversationId = (typeof ConversationManager !== 'undefined' && ConversationManager.activeConversationId)
        ? ConversationManager.activeConversationId : null;
    if (!conversationId) { console.error('No active conversation for delete'); return; }
    $(this).closest('.card').remove();
    reindexMessageCards();
    ChatManager.deleteMessage(conversationId, messageId, messageIndex);
});

$(document).on('click', '.delete-pair-button', function(e) {
    e.preventDefault();
    e.stopPropagation();
    var $btn = $(this);
    var messageId = $btn.attr('message-id');
    var messageIndex = $btn.attr('message-index');
    var sender = $btn.attr('message-sender');
    var conversationId = (typeof ConversationManager !== 'undefined' && ConversationManager.activeConversationId)
        ? ConversationManager.activeConversationId : null;
    if (!conversationId) { console.error('No active conversation for delete pair'); return; }
    var $clickedCard = $btn.closest('.card.message-card');
    ChatManager.deleteMessagePair(conversationId, messageId, messageIndex).done(function(response) {
        var $partnerCard;
        if (sender === 'user') {
            $partnerCard = $clickedCard.next('.card.message-card');
        } else {
            $partnerCard = $clickedCard.prev('.card.message-card');
        }
        $clickedCard.remove();
        if ($partnerCard && $partnerCard.length) $partnerCard.remove();
        reindexMessageCards();
    }).fail(function(xhr) {
        var msg = 'Failed to delete message pair';
        try { msg = JSON.parse(xhr.responseText).error || msg; } catch(_) {}
        if (typeof showToast === 'function') {
            showToast(msg, 'danger');
        } else {
            alert(msg);
        }
    });
});

// Delegated handler for move-pair-as-doubt-button (survives re-renders)
$(document).on('click', '.move-pair-as-doubt-button', function(e) {
    e.preventDefault();
    e.stopPropagation();
    var $btn = $(this);
    var messageId = $btn.attr('message-id');
    var messageIndex = $btn.attr('message-index');
    var sender = $btn.attr('message-sender');
    var conversationId = (typeof ConversationManager !== 'undefined' && ConversationManager.activeConversationId)
        ? ConversationManager.activeConversationId : null;
    if (!conversationId) { console.error('No active conversation for move pair as doubt'); return; }

    var $clickedCard = $btn.closest('.card.message-card');

    // Find partner card (same sibling logic as delete-pair)
    var $partnerCard;
    if (sender === 'user') {
        $partnerCard = $clickedCard.next('.card.message-card');
    } else {
        $partnerCard = $clickedCard.prev('.card.message-card');
    }

    // Find the preceding card (target assistant message whose doubt list we attach to)
    // The user card is always the earlier of the two; we need the card before it.
    var $userCard = (sender === 'user') ? $clickedCard : $partnerCard;
    var $targetCard = $userCard.prev('.card.message-card');

    $.ajax({
        url: '/move_pair_as_doubt/' + conversationId + '/' + messageId + '/' + messageIndex,
        type: 'POST',
        success: function(response) {
            // Remove both pair cards from the DOM
            $clickedCard.remove();
            if ($partnerCard && $partnerCard.length) $partnerCard.remove();
            reindexMessageCards();

            // Reveal the doubts indicator on the target (preceding assistant) card
            var targetMessageId = response.target_message_id;
            if (targetMessageId && $targetCard && $targetCard.length) {
                $targetCard.find('.has-doubts-btn[message-id="' + targetMessageId + '"]').show();
            }

            if (typeof showToast === 'function') {
                showToast('Pair moved to doubts', 'success');
            }
        },
        error: function(xhr) {
            var msg = 'Failed to move pair as doubt';
            try { msg = JSON.parse(xhr.responseText).error || msg; } catch(_) {}
            if (typeof showToast === 'function') {
                showToast(msg, 'danger');
            } else {
                alert(msg);
            }
        }
    });
});

// Delegated handler for has-doubts-btn (survives re-renders)
$(document).on('click', '.has-doubts-btn', function(e) {
    e.preventDefault();
    e.stopPropagation();
    var messageId = $(this).attr('message-id');
    var conversationId = (typeof ConversationManager !== 'undefined' && ConversationManager.activeConversationId)
        ? ConversationManager.activeConversationId : null;
    if (conversationId && messageId && messageId !== 'undefined') {
        DoubtManager.showDoubtsOverview(conversationId, messageId);
    }
});

// Delegated handler for move-message-up/down-button (survives snapshot restore)
$(document).on('click', '.move-message-up-button, .move-message-down-button', function(e) {
    e.preventDefault();
    e.stopPropagation();
    var direction = $(this).hasClass('move-message-up-button') ? 'up' : 'down';
    var messageId = $(this).attr('message-id');
    var ids = [];
    $(".history-message-checkbox:checked").each(function() {
        ids.push($(this).attr('message-id'));
        $(this).prop('checked', false);
    });
    if (messageId) ids.push(messageId);
    if (!ids.length) return;
    ChatManager.moveMessagesUpOrDown(ids, direction).done(function() {
        var selectedCards = [];
        ids.forEach(function(id) {
            var card = $('[message-id="' + id + '"]').closest('.card');
            if (card.length) selectedCards.push(card);
        });
        selectedCards.sort(function(a, b) { return a.index() - b.index(); });
        if (direction === 'up') {
            selectedCards.forEach(function(card) {
                var prev = card.prev('.card');
                if (prev.length) card.insertBefore(prev);
            });
        } else {
            selectedCards.reverse().forEach(function(card) {
                var next = card.next('.card');
                if (next.length) card.insertAfter(next);
            });
        }
    });
});

$(document).on('click', '.show-doubts-button', function(e) {
    e.preventDefault();
    e.stopPropagation();
    var messageId = $(this).attr('message-id');
    var conversationId = (typeof ConversationManager !== 'undefined' && ConversationManager.activeConversationId)
        ? ConversationManager.activeConversationId : null;
    if (!conversationId || typeof DoubtManager === 'undefined') return;
    DoubtManager.showDoubtsOverview(conversationId, messageId);
});

$(document).on('click', '.ask-doubt-button', function(e) {
    e.preventDefault();
    e.stopPropagation();
    var messageId = $(this).attr('message-id');
    var conversationId = (typeof ConversationManager !== 'undefined' && ConversationManager.activeConversationId)
        ? ConversationManager.activeConversationId : null;
    if (!conversationId || typeof DoubtManager === 'undefined') return;
    DoubtManager.askNewDoubt(conversationId, messageId);
});

$(document).on('click', '.open-artefacts-button', function(e) {
    e.preventDefault();
    e.stopPropagation();
    var conversationId = (typeof ConversationManager !== 'undefined' && ConversationManager.activeConversationId)
        ? ConversationManager.activeConversationId : null;
    if (!conversationId) return;
    if (typeof ArtefactsManager !== 'undefined') {
        ArtefactsManager.openModal(conversationId);
    } else {
        if (typeof showToast === 'function') showToast('Artefacts manager not loaded', 'error');
    }
});

$(document).on('click', '.message-ref-badge', function(e) {
    e.preventDefault();
    e.stopPropagation();
    var hash = $(this).data('msg-hash');
    var idx = $(this).data('msg-idx');
    var convFid = (typeof ConversationManager !== 'undefined' && ConversationManager.activeConversationFriendlyId)
        ? ConversationManager.activeConversationFriendlyId : '';
    if (!convFid) return;
    var msgPart = hash ? hash : idx;
    var ref = '@conversation_' + convFid + '_message_' + msgPart;
    var badge = $(this);
    navigator.clipboard.writeText(ref).then(function () {
        var original = badge.text();
        badge.text('Copied!');
        setTimeout(function () { badge.text(original); }, 1200);
    });
});

// Delegated handler for fork-from-here-button (survives DOM replacement).
// Previously only direct-bound inside renderMessages on every render call;
// moving it here means it is registered once and always works regardless of
// when the button appears in the DOM.
$(document).on('click', '.fork-from-here-button', function(e) {
    e.preventDefault();
    e.stopPropagation();
    var msgIndex = parseInt($(this).attr('message-index'), 10);
    if (isNaN(msgIndex)) return;
    var conversationId = (typeof ConversationManager !== 'undefined' && ConversationManager.activeConversationId)
        ? ConversationManager.activeConversationId : null;
    if (!conversationId) return;
    $.ajax({
        url: '/fork_conversation/' + conversationId + '/' + msgIndex,
        type: 'POST',
        success: function(data) {
            if (typeof showToast === 'function') showToast('Forked conversation', 'success');
            if (data.conversation_id) {
                WorkspaceManager.loadConversationsWithWorkspaces(false).done(function() {
                    ConversationManager.setActiveConversation(data.conversation_id);
                    WorkspaceManager.highlightActiveConversation(data.conversation_id);
                });
            }
        },
        error: function() {
            if (typeof showToast === 'function') showToast('Fork failed', 'error');
        }
    });
});

const markdownParser = new marked.Renderer();

// Create a marked extension for math
const mathExtension = {
    name: 'math',
    level: 'block',
    start(src) { return src.match(/^\$\$/)?.index; },
    tokenizer(src, tokens) {
        const rule = /^\$\$([\s\S]*?)\$\$/;
        const match = rule.exec(src);
        if (match) {
            return {
                type: 'math',
                raw: match[0],
                text: match[1].trim()
            };
        }
    },
    renderer(token) {
        return `$$${token.text}$$`;
    }
};

// Configure marked with the math extension
marked.use({ extensions: [mathExtension] });

marked.setOptions({
    renderer: markdownParser,
    pedantic: false,
    gfm: true,
    breaks: false,
    sanitize: false,
    smartLists: true,
    smartypants: false,
    xhtml: true
});
markdownParser.table = function(header, body) {
    return '<div class="table-responsive" style="overflow-x:auto;"><table>' + header + body + '</table></div>';
};
markdownParser.text = function(text) {
    // Preserve math delimiters from being processed
    // This prevents marked from interfering with $ signs
    return text;
};

const options = {
    throwOnError: false,
    nonStandard: true,
    // Mirror the custom macros from the MathJax config (interface.html)
    // so KaTeX can render them without MathJax fallback.
    macros: {
      "\\RR": "\\mathbb{R}",
      "\\bold": "\\mathbf{#1}",
      "\\red": "\\color{red}{#1}"
    },
    // When _DISABLE_MATHJAX is true, output HTML-only (no MathML annotation)
    // so MathJax's mml2jax preprocessor has nothing to find.  When MathJax is
    // enabled, keep htmlAndMathml so MathJax can re-typeset the MathML if desired.
    output: window._DISABLE_MATHJAX ? 'html' : 'htmlAndMathml',
  };

marked.use(markedKatex(options));


/**
 * Normalize over-indented list items that the markdown parser would treat as
 * indented code blocks.
 *
 * In standard CommonMark / GFM markdown, 4 or more spaces of leading
 * indentation creates an "indented code block".  Many LLMs format bullet
 * points with 4-space indentation (e.g., "    *   text"), which causes
 * `marked` to wrap them in `<pre><code>` instead of rendering them as list
 * items with inline math / formatting.
 *
 * This function detects lines that:
 *   1. Have 4+ spaces of leading whitespace, AND
 *   2. Start with a list marker (`*`, `-`, `+`, or `1.` etc.)
 * and removes exactly 4 spaces of indentation.  Subtracting 4 (rather than
 * stripping to zero) preserves relative nesting:
 *   - `    *  item`   → `*  item`       (top-level)
 *   - `        * sub` → `    * sub`     (nested; still valid inside the list)
 *
 * Continuation lines (non-list, non-blank lines that follow a de-indented
 * list item and also have 4+ spaces) are de-indented too, so wrapped bullet
 * text doesn't become a code block.
 *
 * Fenced code blocks (```, ~~~) are skipped entirely so legitimate code is
 * never modified.
 *
 * @param {string} text  Raw markdown text before parsing
 * @returns {string}     Text with over-indented list items normalised
 */
function normalizeOverIndentedLists(text) {
    if (!text) return text;

    var lines = text.split('\n');
    var inCodeBlock = false;
    var deindenting = false;  // are we in a "run" of lines being de-indented?

    for (var i = 0; i < lines.length; i++) {
        var line = lines[i];
        // Compute trimmed + leading-space count without mutating `line`
        var trimmed = line.replace(/^\s+/, '');
        var leadingSpaces = line.length - trimmed.length;

        // ── Track fenced code blocks ─────────────────────────────────
        if (trimmed.startsWith('```') || trimmed.startsWith('~~~')) {
            inCodeBlock = !inCodeBlock;
            deindenting = false;
            continue;
        }
        if (inCodeBlock) continue;

        // ── Detect list markers ──────────────────────────────────────
        var isListItem = /^[\*\-\+]\s/.test(trimmed) || /^\d+\.\s/.test(trimmed);

        if (isListItem && leadingSpaces >= 4) {
            // Over-indented list item → subtract 4 spaces
            lines[i] = line.substring(4);
            deindenting = true;
        } else if (deindenting && leadingSpaces >= 4 && trimmed !== '') {
            // Continuation line of a de-indented list item
            // (still has 4+ spaces and is non-blank → de-indent too)
            lines[i] = line.substring(4);
        } else if (trimmed === '') {
            // Blank lines: keep the de-indent state alive
            // (blank lines between list items are normal)
        } else if (leadingSpaces < 4) {
            // Non-indented / lightly-indented content → end the run
            deindenting = false;
        }
    }

    return lines.join('\n');
}

/**
 * Strip trailing whitespace that the streaming layer's `.replace(/\n/g, '  \n')`
 * injects inside `$$ ... $$` display-math blocks.
 *
 * The marked-katex-extension's block regex requires `$$\n` (dollar-dollar
 * immediately followed by newline) to recognise a display math block.  The
 * streaming soft-break injection turns that into `$$  \n`, which breaks the
 * regex, so `blockKatex` never matches.  The content then falls through to
 * the custom `mathExtension` passthrough → MathJax.  When MathJax is disabled,
 * nothing renders the block and the user sees raw LaTeX.
 *
 * This function:
 *   1. Strips trailing spaces from standalone `$$` delimiter lines so the
 *      block regex matches (`$$  \n` → `$$\n`).
 *   2. Strips trailing spaces from every line INSIDE a `$$` block so that
 *      LaTeX line-break commands (`\\`) are not followed by stray spaces
 *      that could confuse KaTeX.
 *   3. Skips fenced code blocks (``` / ~~~) entirely.
 *
 * Must be called BEFORE `marked.marked()`.
 *
 * @param {string} text  Raw markdown text (possibly with injected trailing spaces)
 * @returns {string}     Text with display-math blocks cleaned up
 */
function normalizeMathBlocks(text) {
    if (!text) return text;

    var lines = text.split('\n');
    var inCodeBlock = false;
    var inMathBlock = false;

    for (var i = 0; i < lines.length; i++) {
        // Strip leading whitespace and blockquote markers (> ) for detection only.
        // Blockquoted math looks like: "> $$", "> > $$", ">  \begin{align}" etc.
        var trimmed = lines[i].replace(/^[\s>]+/, '');

        // Track fenced code blocks — never touch content inside them
        if (trimmed.startsWith('```') || trimmed.startsWith('~~~')) {
            inCodeBlock = !inCodeBlock;
            continue;
        }
        if (inCodeBlock) continue;

        // Detect standalone $$ delimiter (possibly with trailing spaces)
        var isDollarDelimiter = /^\$\$\s*$/.test(trimmed);

        if (isDollarDelimiter) {
            // Strip trailing spaces from the delimiter line itself
            lines[i] = lines[i].replace(/\s+$/, '');
            inMathBlock = !inMathBlock;
            continue;
        }

        // Inside a math block, strip trailing spaces from every line
        if (inMathBlock) {
            lines[i] = lines[i].replace(/\s+$/, '');
        }
    }

    return lines.join('\n');
}


/**
 * Build a standalone HTML document string that renders the given slides HTML
 * inside a Reveal.js deck.
 * The provided slidesHtml must include <section> elements only.
 */
function buildStandaloneSlidesPage(slidesHtml) {
    return `<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Slides</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/reveal.js@4.3.1/dist/reveal.css">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/reveal.js@4.3.1/dist/theme/white.css">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/reveal.js@4.3.1/plugin/highlight/monokai.css">
    <style>
        body, html { margin: 0; padding: 0; height: 100%; }
        .reveal { height: 100%; background: #fff; }
        .reveal .slides section { text-align: left; }
    </style>
</head>
<body>
    <div class="reveal">
        <div class="slides">
            ${slidesHtml}
        </div>
    </div>
    <script src="https://cdn.jsdelivr.net/npm/reveal.js@4.3.1/dist/reveal.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/reveal.js@4.3.1/plugin/notes/notes.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/reveal.js@4.3.1/plugin/highlight/highlight.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/reveal.js@4.3.1/plugin/math/math.js"></script>
    <script>
        (function() {
            const deck = new Reveal(document.querySelector('.reveal'), {
                embedded: false,
                // IMPORTANT: Disable hash/history for blob/about pages to avoid SecurityError
                hash: false,
                controls: true,
                progress: true,
                center: false,
                transition: 'slide',
                backgroundTransition: 'fade',
                plugins: [RevealHighlight, RevealMath.KaTeX]
            });
            try { deck.initialize(); } catch (e) { console.error('Reveal init error:', e); }
        })();
    </script>
  </body>
</html>`;
}

/**
 * Detect if provided HTML is a full HTML document (has <!DOCTYPE html> or <html> root)
 */
function isFullHtmlDocument(htmlString) {
    if (!htmlString || typeof htmlString !== 'string') return false;
    var s = htmlString.trim();
    return (/^<!DOCTYPE\s+html/i.test(s) || /^<html[\s>]/i.test(s));
}

/**
 * If given embedded Reveal markup, extract only the direct <section>…</section> nodes
 * contained inside the first <div class="slides">…</div>. If not found, returns input.
 */
function extractSectionsFromReveal(htmlString) {
    if (!htmlString || typeof htmlString !== 'string') return htmlString;
    var match = htmlString.match(/<div[^>]*class=["']?slides["']?[^>]*>([\s\S]*?)<\/div>/i);
    if (match && match[1]) {
        return match[1].trim();
    }
    return htmlString;
}

/**
 * Split content into an ordered list of parts around <slide-presentation>…</slide-presentation> blocks.
 * Returns { parts: Array<{type: 'text'|'slide', content: string}>, incomplete: boolean }
 * If a closing tag is missing (streaming), 'incomplete' is true and only text before the
 * opening tag will be returned in parts.
 */
function splitSlidePresentationParts(htmlString) {
    var parts = [];
    var i = 0;
    var startTag = '<slide-presentation>';
    var endTag = '</slide-presentation>';
    while (i < htmlString.length) {
        var startIdx = htmlString.indexOf(startTag, i);
        if (startIdx === -1) {
            // remaining text
            parts.push({ type: 'text', content: htmlString.slice(i) });
            break;
        }
        // text before slide
        if (startIdx > i) {
            parts.push({ type: 'text', content: htmlString.slice(i, startIdx) });
        }
        var endIdx = htmlString.indexOf(endTag, startIdx + startTag.length);
        if (endIdx === -1) {
            // Incomplete slide block (streaming). Stop here; don't include partial slide
            return { parts: parts, incomplete: true };
        }
        // Extract inner slide content
        var inner = htmlString.slice(startIdx + startTag.length, endIdx);
        parts.push({ type: 'slide', content: inner });
        i = endIdx + endTag.length;
    }
    return { parts: parts, incomplete: false };
}

/**
 * Create a blob URL for the provided HTML string so it can be opened in a new window.
 */
function createSlidesBlobUrl(htmlString) {
    try {
        const blob = new Blob([htmlString], { type: 'text/html;charset=utf-8' });
        return URL.createObjectURL(blob);
    } catch (e) {
        console.error('Failed to create slides blob URL', e);
        return 'about:blank';
    }
}

markdownParser.codespan = function (text) {
    return '<code class="inline-code">' + text + '</code>';
};
// LLM alias → hljs language name map. LLMs frequently emit short aliases
// (e.g. ```py, ```js, ```ts) that hljs doesn't recognise, causing a fallback
// to unhighlighted plaintext. This map rescues those blocks cheaply (O(1) lookup).
var _hljsAliasMap = {
    'py': 'python', 'py3': 'python', 'python3': 'python',
    'js': 'javascript', 'jsx': 'javascript', 'mjs': 'javascript', 'cjs': 'javascript',
    'ts': 'typescript', 'tsx': 'typescript',
    'sh': 'bash', 'zsh': 'bash', 'shell': 'bash', 'console': 'bash',
    'yml': 'yaml',
    'md': 'markdown',
    'rb': 'ruby',
    'rs': 'rust',
    'cs': 'csharp', 'c#': 'csharp',
    'c++': 'cpp', 'cc': 'cpp', 'cxx': 'cpp', 'h': 'cpp', 'hpp': 'cpp',
    'objc': 'objectivec', 'objective-c': 'objectivec',
    'kt': 'kotlin', 'kts': 'kotlin',
    'html': 'xml', 'htm': 'xml', 'svg': 'xml', 'xhtml': 'xml',
    'jsonc': 'json', 'json5': 'json',
    'toml': 'ini',
    'text': 'plaintext', 'txt': 'plaintext', 'raw': 'plaintext', 'log': 'plaintext',
    'psql': 'sql', 'mysql': 'sql', 'sqlite': 'sql',
    'dockerfile': 'bash',      // close-enough highlighting
    'makefile': 'makefile',
};

// Fast HTML-escape for plaintext code blocks (no hljs call needed).
function _escapeCodeHtml(str) {
    return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

markdownParser.code = function (code, language) {
    if (code.trim().startsWith('<div class="section-footer">')) {
        return code;
    }
    // Mermaid: render diagram duplicate + keep original code block for copy-btn.
    // The <pre class="mermaid"> clone is what mermaid.run() targets.
    // The original <pre><code> source is preserved inside a <details> so the
    // copy button still has the raw source to copy.
    if (language === 'mermaid') {
        var escapedCode = _escapeCodeHtml(code);
        return '<div class="code-block mermaid-container">' +
            '<pre class="mermaid">' + code + '</pre>' +
            '<details class="mermaid-source-block">' +
                '<summary style="font-size:11px;color:#888;cursor:pointer;">Mermaid source</summary>' +
                '<pre><code class="hljs language-mermaid">' + escapedCode + '</code></pre>' +
            '</details>' +
            '</div>';
    }

    // ── Language resolution (O(1)) ──
    // 1. Normalise to lowercase, strip leading/trailing whitespace.
    // 2. Check alias map for common LLM shorthands (py → python, js → javascript …).
    // 3. Verify with hljs.getLanguage(); fall back to plaintext if unknown.
    // This replaces the old path that called hljs.highlightAuto() (~50-200 ms per block)
    // whenever the language was unrecognised.
    var lang = (language || '').trim().toLowerCase();
    if (lang && _hljsAliasMap[lang]) {
        lang = _hljsAliasMap[lang];
    }
    if (!lang || !hljs.getLanguage(lang)) {
        lang = 'plaintext';
    }

    // ── Highlight ──
    // Plaintext: skip hljs entirely — just HTML-escape. Saves the function-call overhead
    // and, critically, avoids the old highlightAuto() auto-detection that tested against
    // all 37 registered grammars.
    var highlighted;
    if (lang === 'plaintext') {
        highlighted = _escapeCodeHtml(code);
    } else {
        highlighted = hljs.highlight(code, { language: lang }).value;
    }

    var number_of_lines = code.split('\n').length;
    var show_by_default = number_of_lines < 8
        || ((lang === 'markdown' || lang === 'md') && number_of_lines < 15)
        || (lang === 'plaintext' && number_of_lines < 15);
    if (show_by_default) {
        return '<div class="code-block">' +
            '<pre><code class="hljs ' + (language || '') + '">' + highlighted + '</code></pre>' +
            '</div>';
    } else {
        return '<div class="code-block">' +
            '<div class="code-header" style="height: 18px; min-height: 16px; padding: 1px 4px; display: flex; align-items: center; justify-content: space-between;">' +
                '<button class="copy-code-btn" style="padding: 2px 2px; font-size: 12px; height: 20px;">Copy</button>' +
            '</div>' +
            '<details style="padding-top: 20px;">' +
                '<summary>Code Block</summary>' +
                '<pre><code class="hljs ' + (language || '') + '">' + highlighted + '</code></pre>' +
            '</details>' +
            '</div>';
    }
};

function hasUnclosedMermaidTag(htmlString) {
    // Regular expression to identify all relevant mermaid tags
    // Updated to handle both single and double quotes, and flexible whitespace
    const tagRegex = /<pre\s+class=["']mermaid["']>|<\/pre>|```mermaid|```(?!\w)/g;
    let stack = [];
    let match;

    while ((match = tagRegex.exec(htmlString)) !== null) {
        if (match[0].startsWith("<pre")) {
            // Push the expected closing tag for <pre class='mermaid'> or <pre class="mermaid">
            stack.push("</pre>");
        } else if (match[0] === "```mermaid") {
            // Push the expected closing tag for ```mermaid
            stack.push("```");
        } else if (match[0] === "</pre>" || match[0] === "```") {
            // Check if the closing tag matches the expected one from the stack
            if (stack.length === 0 || stack.pop() !== match[0]) {
                return true; // Mismatch found or stack is empty (unmatched closing tag)
            }
        }
    }

    return stack.length > 0; // If the stack is not empty, there is at least one unclosed tag
}
 
function normalizeMermaidText(text) {
    /**
     * Normalize unicode characters that commonly break Mermaid parsing/rendering.
     *
     * Replaces:
     * - NBSP (U+00A0) and narrow NBSP (U+202F) with a normal space
     * - “ ” with "
     * - ‘ ’ with '
     *
     * @param {string} text - Mermaid source (or wrapper text containing Mermaid source)
     * @returns {string} - Normalized text
     */
    if (text === null || text === undefined) {
        return text;
    }
    if (typeof text !== 'string') {
        text = String(text);
    }
    return text
        .replace(/\u00A0/g, ' ')
        .replace(/\u202F/g, ' ')
        .replace(/[“”]/g, '"')
        .replace(/[‘’]/g, "'");
}

function cleanMermaidCode(mermaidCode) {
    /**
     * Prepare Mermaid code for rendering:
     * - Normalize unicode that breaks parsing (NBSP, smart quotes)
     * - Trim trailing whitespace
     * - Remove empty lines and accidental wrapper-tag artifacts
     *
     * @param {string} mermaidCode
     * @returns {string}
     */
    mermaidCode = normalizeMermaidText(mermaidCode || "");
    return mermaidCode
        .split('\n')
        .map(function(line) { return line.trimRight(); })
        .filter(function(line) {
            return line.length > 0 &&
                   !line.includes('pre class="mermaid"') &&
                   !line.includes("pre class='mermaid");
        })
        .join('\n');
}

function normalizeMermaidBlocks(rootElem) {
    /**
     * Normalize Mermaid <pre class="mermaid"> blocks in the DOM before calling mermaid.run().
     *
     * @param {HTMLElement|JQuery|null} rootElem - Root container to scan (defaults to document)
     */
    var $root = rootElem ? $(rootElem) : $(document);
    $root.find('pre.mermaid, .mermaid').each(function(_idx, block) {
        // Avoid rewriting already-rendered blocks (Mermaid replaces with SVG inside)
        if (block && !block.querySelector('svg')) {
            var code = block.textContent || block.innerText || "";
            block.textContent = cleanMermaidCode(code);
        }
    });
}

/**
 * Render any unrendered mermaid blocks inside a jQuery container.
 * Safe to call repeatedly — skips blocks that already contain an SVG.
 * On syntax errors, shows a "Fix Diagram" button that calls the LLM.
 * @param {jQuery} $container
 */
function renderMermaidIn($container) {
    if (typeof mermaid === 'undefined') return;
    var blocks = $container.find('pre.mermaid').filter(function() {
        return !this.querySelector('svg') && !this.getAttribute('data-mermaid-failed');
    });
    if (!blocks.length) return;

    // Store original source before mermaid mutates it
    var sources = [];
    blocks.each(function(i) {
        sources[i] = cleanMermaidCode(this.textContent || '');
        this.textContent = sources[i];
        this.setAttribute('data-mermaid-source', sources[i]);
    });

    mermaid.run({ nodes: blocks.toArray(), useMaxWidth: false, suppressErrors: true })
        .then(function() {
            blocks.each(function(i) {
                var svg = this.querySelector('svg');
                if (!svg) return;
                $(svg).attr('height', null);
                // Detect error: mermaid error SVGs contain .error-text or "Syntax error"
                var isError = svg.querySelector('.error-text') ||
                    (svg.textContent || '').indexOf('Syntax error') !== -1 ||
                    (svg.getAttribute('aria-roledescription') || '') === '';
                if (isError && sources[i]) {
                    _showMermaidFixButton(this, sources[i], $container);
                }
            });
        })
        .catch(function() {
            // Total failure — all blocks errored
            blocks.each(function(i) {
                if (sources[i]) {
                    _showMermaidFixButton(this, sources[i], $container);
                }
            });
        });
}

function _showMermaidFixButton(block, source, $container) {
    block.setAttribute('data-mermaid-failed', 'true');
    var $block = $(block);
    // Show source code instead of error SVG
    $block.empty().text(source).css({ 'font-size': '12px', 'opacity': '0.6', 'white-space': 'pre-wrap' });
    var $btn = $('<button class="btn btn-sm btn-outline-warning mt-1" style="font-size:11px;">⚠️ Fix Diagram</button>');
    $block.after($btn);
    $btn.one('click', function() {
        $btn.prop('disabled', true).text('Fixing...');
        // Get surrounding answer text for context
        var answerContext = '';
        try {
            var $card = $container.closest('.card-body, .model-tab-body, .doubt-conversation-card');
            answerContext = ($card.text() || '').substring(0, 3000);
        } catch (e) { /* ignore */ }
        // Call LLM to fix
        $.ajax({
            url: '/temporary_llm_action',
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({
                action_type: 'ask_temp',
                selected_text: source,
                user_message: 'This mermaid diagram has a syntax error. Output ONLY the corrected mermaid code (no explanation, no markdown fences, just the raw mermaid syntax). Here is the surrounding context for understanding what the diagram should show:\n\n' + answerContext.substring(0, 2000),
                history: [],
                with_context: false
            }),
            success: function(responseText) {
                // Parse streaming response to get accumulated text
                var fixed = '';
                (responseText || '').split('\n').forEach(function(line) {
                    if (!line.trim()) return;
                    try {
                        var chunk = JSON.parse(line);
                        if (chunk.text) fixed += chunk.text;
                    } catch (e) { /* ignore */ }
                });
                fixed = cleanMermaidCode(fixed.replace(/```mermaid/g, '').replace(/```/g, '').trim());
                if (fixed.length > 10) {
                    $btn.remove();
                    block.removeAttribute('data-mermaid-failed');
                    block.textContent = fixed;
                    $(block).css({ 'font-size': '', 'opacity': '', 'white-space': '' });
                    mermaid.run({ nodes: [block], useMaxWidth: false, suppressErrors: true })
                        .then(function() {
                            var svg = block.querySelector('svg');
                            if (svg) $(svg).attr('height', null);
                        })
                        .catch(function() {
                            block.setAttribute('data-mermaid-failed', 'true');
                            $(block).text(fixed).css({ 'font-size': '12px', 'opacity': '0.6', 'white-space': 'pre-wrap' });
                            $(block).after('<small class="text-danger">Fix failed — syntax still invalid</small>');
                        });
                } else {
                    $btn.text('Fix failed').addClass('btn-outline-danger');
                }
            },
            error: function() {
                $btn.text('Fix failed').addClass('btn-outline-danger');
            }
        });
    });
}

function normalizeTextForClipboard(textElem, textToCopy, mode) {
    /**
     * Guard clipboard copy for Mermaid/code-like text without touching normal prose.
     *
     * @param {HTMLElement|JQuery|null} textElem
     * @param {string} textToCopy
     * @param {string} mode
     * @returns {string}
     */
    if (textToCopy === null || textToCopy === undefined) {
        return textToCopy;
    }
    var text = (typeof textToCopy === 'string') ? textToCopy : String(textToCopy);

    // Always normalize for explicitly code-oriented copy modes.
    if (mode === "code" || mode === "codemirror") {
        return normalizeMermaidText(text);
    }

    // For generic "text" copies, normalize only if it looks like Mermaid/markdown code.
    var looksLikeMermaidOrCode =
        text.indexOf("```") !== -1 ||
        text.toLowerCase().indexOf("```mermaid") !== -1 ||
        text.toLowerCase().indexOf('<pre class="mermaid"') !== -1 ||
        text.toLowerCase().indexOf('class="mermaid"') !== -1;

    if (!looksLikeMermaidOrCode && textElem) {
        try {
            if ($(textElem).closest('pre.mermaid, .mermaid, code.language-mermaid').length > 0) {
                looksLikeMermaidOrCode = true;
            }
        } catch (e) { /* ignore */ }
    }

    return looksLikeMermaidOrCode ? normalizeMermaidText(text) : text;
}

function applyModelResponseTabs(elem_to_render_in) {
    var $root = elem_to_render_in ? $(elem_to_render_in) : $(document);
    
    // Scroll preservation uses a TWO-LEVEL strategy:
    // 1. OUTER level: renderInnerContentAsMarkdown() captures scrollTop BEFORE innerHTML and
    //    restores AFTER all synchronous work (including showMore + this function) completes.
    // 2. INNER level (here): We capture scrollTop RIGHT BEFORE the insert/hide DOM swap and
    //    restore RIGHT AFTER. This covers calls from showMore() toggle and other non-render paths.
    // Both levels use immediate restore + requestAnimationFrame + setTimeout retries.

    // Chat UI responses can involve multiple sibling render containers under a single
    // `.chat-card-body` (e.g., `#message-render-space` and `#message-render-space-md-render`,
    // plus showMore() wrappers). For tabbed responses we need to:
    // - insert a single tabs UI in a stable place
    // - hide *all* source render containers so the answer doesn't duplicate above/below tabs
    //
    // Multi-model responses already hide their `<details>` sources; single-model+TLDR relies
    // primarily on sibling hiding. Using the `.chat-card-body` as the scope makes both modes
    // behave consistently.
    try {
        var $chatBody = $root.closest('.chat-card-body');
        if ($chatBody.length > 0) {
            $root = $chatBody;
        }
    } catch (e) { /* ignore */ }

    var rootEl = $root[0];

    // ── B: Fast cache check ──────────────────────────────────────────────
    // On a previous call that early-exited ("no tabs needed"), we stamp
    // data-no-tabs="1" on $root.  If the attribute is still present, the
    // card body hasn't been rebuilt (innerHTML is only set on the inner
    // render element, not the card body), so the answer is unchanged and
    // we can skip all DOM discovery work.  The attribute is cleared whenever
    // tabs ARE built (data-has-tabs is set instead).
    if (rootEl && rootEl.getAttribute('data-no-tabs') === '1') {
        return;
    }

    // ── D: Native DOM fast-path for "no tabs needed" ─────────────────────
    // Before building any jQuery collections, use native querySelector to
    // check whether any tab-worthy content exists.  This replaces 5-7
    // jQuery .find() traversals (~5ms each) with 3-4 native calls (<0.5ms).
    //
    // Tab-worthy content:
    //   1. Non-section <details> blocks (multi-model, TLDR fallback, etc.)
    //   2. [data-answer-tldr] wrappers
    //   3. [data-answer-visual] wrappers
    //   4. An existing .model-tabs-container (re-render / cleanup path)
    //
    // Section-only <details class="section-details"> never need tabs.
    if (rootEl) {
        var _hasExistingContainer = rootEl.querySelector('.model-tabs-container');
        // If there's no existing container AND no tab-worthy content, early-exit.
        // When there IS an existing container, we must continue (may need to clean it up).
        if (!_hasExistingContainer) {
            var _hasNonSectionDetails = rootEl.querySelector('details:not(.section-details)');
            var _hasTldr = rootEl.querySelector('[data-answer-tldr]');
            var _hasVisual = rootEl.querySelector('[data-answer-visual]');
            if (!_hasNonSectionDetails && !_hasTldr && !_hasVisual) {
                // No tabs needed — stamp cache attribute and return
                rootEl.setAttribute('data-no-tabs', '1');
                rootEl.removeAttribute('data-has-tabs');
                return;
            }
        }
    }

    // ── Past the fast-path: clear the no-tabs cache (we may build tabs) ──
    if (rootEl) rootEl.removeAttribute('data-no-tabs');

    var $legacySource = $root.find('.model-tabs-source').first();
    if ($legacySource.length > 0) {
        $legacySource.find('details').not('.section-details').each(function() {
            $root.append($(this));
        });
        $legacySource.find('[data-answer-tldr]').each(function() {
            $root.append($(this));
        });
        $legacySource.remove();
    }

    var rootId = $root.attr('id');
    if (!rootId) {
        rootId = $root.attr('data-model-tabs-id');
        if (!rootId) {
            rootId = 'model-tabs-root-' + Date.now().toString(36) + Math.random().toString(36).substr(2, 6);
            $root.attr('data-model-tabs-id', rootId);
        }
    }

    // Prefer a container that is a direct child of the message body.
    // If an older render left it nested inside the answer DOM, move it to the top-level.
    var $existingContainer = $root.children('.model-tabs-container').first();
    if ($existingContainer.length === 0) {
        $existingContainer = $root.find('.model-tabs-container').first();
        if ($existingContainer.length > 0) {
            try { $root.prepend($existingContainer); } catch (e) { /* ignore */ }
        }
    }
    var activeTabKey = '';
    var scrollTop = 0;
    if ($existingContainer.length > 0) {
        activeTabKey = $existingContainer.find('.nav-link.active').attr('data-tab-key') || '';
        scrollTop = $existingContainer.find('.tab-content').scrollTop();
    }

    // If we're re-applying tabs (e.g., showMore() rebuild or reload snapshot), the
    // original TLDR sources may already be removed from the DOM. Preserve TLDR content
    // from the existing tab container early so we don't mistakenly remove tabs.
    var preservedTldrContent = null;
    try {
        if ($existingContainer.length > 0) {
            var $existingTldrPane = $existingContainer.find('[id$="-pane-tldr"]').first();
            if ($existingTldrPane.length > 0) {
                var $existingTldrBody = $existingTldrPane.find('.model-tab-body').first();
                if ($existingTldrBody.length > 0 && hasMeaningfulContent($existingTldrBody)) {
                    preservedTldrContent = $existingTldrBody.clone(true, true);
                }
            }
        }
    } catch (e) { preservedTldrContent = null; }

    var $detailsBlocks = $root.find('details').not('.section-details').not('.model-tabs-container details');
    var $tldrWrapper = $root.find('[data-answer-tldr]').first();
    // Check for meaningful content in TLDR wrapper, not just any content (fixes empty TLDR tab issue)
    var hasTldrWrapper = $tldrWrapper.length > 0 && hasMeaningfulContent($tldrWrapper);
    var $visualWrapper = $root.find('[data-answer-visual]').first();
    var hasVisualWrapper = $visualWrapper.length > 0 && hasMeaningfulContent($visualWrapper);
    var $tldrFallbackDetails = $root.find('details').filter(function() {
        var summaryText = ($(this).find('> summary').first().text() || '').trim().toLowerCase();
        return summaryText.indexOf('tldr') !== -1;
    }).not('.section-details').not('.model-tabs-container details');

    // DIAGNOSTIC: Log what applyModelResponseTabs found
    if (!isLiveStreaming) {
        // [DEBUG] console.warn('[applyModelResponseTabs] $root:', $root.prop('tagName'), $root.attr('class'), '| visualWrapper:', $visualWrapper.length, '| hasVisualWrapper:', hasVisualWrapper, '| tldrWrapper:', $tldrWrapper.length, '| hasTldrWrapper:', hasTldrWrapper, '| isLiveStreaming:', isLiveStreaming);
    }
    if ($detailsBlocks.length > 0) {
        $detailsBlocks.each(function(i) {
            var sum = ($(this).find('> summary').first().text() || '').trim();
            // console.warn('[applyModelResponseTabs] details[' + i + ']:', sum);
        });
    }

    if ($detailsBlocks.length === 0 && !hasTldrWrapper && preservedTldrContent === null) {
        // No tabs needed — no details blocks, no TLDR wrapper, no preserved content
        if ($existingContainer.length > 0) {
            $existingContainer.remove();
        }
        $root.removeAttr('data-has-tabs');
        // Cache the "no tabs" decision so subsequent calls (showMore expand, re-render)
        // can skip all DOM discovery via the fast-path at the top of this function.
        if (rootEl) rootEl.setAttribute('data-no-tabs', '1');
        $root.find('[data-model-tabs-hidden="true"]').show().removeAttr('data-model-tabs-hidden');
        return;
    }

    var modelDetails = [];
    var tldrDetails = [];
    var visualDetails = [];

    function restoreHiddenForClone($elem) {
        if (!$elem || $elem.length === 0) return;
        $elem.removeAttr('data-model-tabs-hidden');
        $elem.find('[data-model-tabs-hidden]').each(function() {
            $(this).removeAttr('data-model-tabs-hidden');
        });
        $elem.find('[style]').each(function() {
            var style = $(this).attr('style') || '';
            if (style.indexOf('display') !== -1) {
                var cleaned = style.replace(/display\s*:\s*none\s*;?/gi, '').trim();
                if (cleaned) {
                    $(this).attr('style', cleaned);
                } else {
                    $(this).removeAttr('style');
                }
            }
        });
        $elem.show();
    }

    $detailsBlocks.each(function(index, el) {
        var $details = $(el);
        var summaryText = ($details.find('> summary').first().text() || '').trim();
        var isModel = summaryText.toLowerCase().indexOf('response from') === 0;
        var isTldr = summaryText.toLowerCase().indexOf('tldr summary') !== -1 || summaryText.toLowerCase().indexOf('tldr') !== -1 || summaryText.indexOf('📝 TLDR Summary') !== -1;
        var isVisual = summaryText.indexOf('🎨') !== -1 || summaryText.toLowerCase().indexOf('visual explanation') !== -1;
        if (!isTldr) {
            var hasTldrAncestor = $details.closest('[data-answer-tldr]').length > 0;
            if (hasTldrAncestor) {
                isTldr = true;
            }
        }
        if (isModel) {
            modelDetails.push({
                summary: summaryText,
                element: $details,
                index: index
            });
        }
        if (isTldr) {
            tldrDetails.push({
                summary: summaryText,
                element: $details,
                index: index
            });
        }
        if (isVisual) {
            visualDetails.push({
                summary: summaryText,
                element: $details,
                index: index
            });
        }
    });

    var groupKey = rootId + '-model-tabs-group';
    var navId = groupKey + '-nav';
    var contentId = groupKey + '-content';

    var $container = $existingContainer.length > 0 ? $existingContainer : $('<div class="model-tabs-container" />');
    
    // Helper function to check if an element has meaningful text content
    // Returns true if there's actual text beyond just whitespace and empty tags
    function hasMeaningfulContent($elem) {
        if (!$elem || $elem.length === 0) return false;
        // Special-case <details>: ignore <summary> text, since TLDR streams the summary header
        // early (e.g., "📝 TLDR Summary...") before the body arrives. Counting summary text
        // causes premature TLDR-tab creation and hides the main answer while TLDR is still streaming.
        try {
            if ($elem.is('details')) {
                var $clone = $elem.clone();
                $clone.find('> summary').first().remove();
                var bodyText = ($clone.text() || '').trim();
                return bodyText.length > 10;
            }
        } catch (e) { /* ignore */ }

        // If this wrapper contains a <details>, prefer checking that detail body (excluding summary).
        try {
            var $innerDetails = $elem.find('details').first();
            if ($innerDetails.length > 0) {
                return hasMeaningfulContent($innerDetails);
            }
        } catch (e) { /* ignore */ }

        // Default: text length threshold
        var textContent = ($elem.text() || '').trim();
        return textContent.length > 10; // Require at least 10 chars of actual content
    }
    
    // Note: preservedTldrContent is computed above (before early-return) so it also works
    // when sources are already removed.
    
    // ========================================================================
    // STEP 1: Validate and clone TLDR content FIRST (before deciding on tabs)
    // This ensures we only show TLDR tab if there's meaningful content
    // ========================================================================
    var tldrContentClone = null;
    if (hasTldrWrapper) {
        // Fresh TLDR from server response - look for details inside wrapper
        var $tldrInnerDetails = $tldrWrapper.find('details').first();
        if ($tldrInnerDetails.length > 0 && hasMeaningfulContent($tldrInnerDetails)) {
            tldrContentClone = $tldrInnerDetails.clone(true, true);
        } else if (hasMeaningfulContent($tldrWrapper)) {
            // Wrapper has content but no details - clone wrapper itself
            tldrContentClone = $tldrWrapper.clone(true, true);
        }
        // If no meaningful content found, tldrContentClone stays null
    } else if (tldrDetails.length > 0) {
        // TLDR from details block - verify it has meaningful content
        var $tldrDetailsElem = tldrDetails[0].element;
        if (hasMeaningfulContent($tldrDetailsElem)) {
            tldrContentClone = $tldrDetailsElem.clone(true, true);
        }
    } else if (preservedTldrContent !== null) {
        // Use preserved content from existing tab container (reload scenario)
        // Already verified to have meaningful content when preserved
        tldrContentClone = preservedTldrContent;
    } else if ($tldrFallbackDetails.length > 0) {
        var $fallbackElem = $tldrFallbackDetails.first();
        if (hasMeaningfulContent($fallbackElem)) {
            tldrContentClone = $fallbackElem.clone(true, true);
        }
    }
    
    // Final check: do we actually have meaningful TLDR content?
    var actuallyHasTldrContent = tldrContentClone !== null && hasMeaningfulContent(tldrContentClone);
    var actuallyHasVisualContent = hasVisualWrapper || (visualDetails.length > 0 && hasMeaningfulContent(visualDetails[0].element));
    
    // Check if this card is currently streaming
    // During live streaming, DON'T build single-model+TLDR tabs because:
    // - The main content is still being streamed to source containers
    // - Building tabs hides those containers, causing main content to "disappear"
    // - The cloned "Main" tab content won't receive streaming updates
    // Multi-model is fine because each model's <details> block is complete.
    var isLiveStreaming = false;
    try {
        var $card = $root.closest('.card.message-card');
        if ($card.length === 0) {
            $card = $root.closest('.card');
        }
        isLiveStreaming = $card.attr('data-live-stream') === 'true';
    } catch (e) { /* ignore */ }
    
    // DIAGNOSTIC: Log tab decision inputs
    // console.warn('[applyModelResponseTabs] models:', modelDetails.length, 'tldr:', actuallyHasTldrContent, 'streaming:', isLiveStreaming);
    
    // ========================================================================
    // STEP 2: Decide whether to build tabs based on validated content
    // ========================================================================
    var shouldBuildTabs = false;
    if (modelDetails.length > 1) {
        // Multiple models = always show tabs (one tab per model)
        // Safe during streaming because each model <details> block is complete
        shouldBuildTabs = true;
    } else if (modelDetails.length === 1 && (actuallyHasTldrContent || actuallyHasVisualContent)) {
        // Single model WITH meaningful TLDR = show tabs (Main + TLDR)
        // But NOT during live streaming - wait until streaming ends
        if (!isLiveStreaming) {
            shouldBuildTabs = true;
        }
    } else if (modelDetails.length === 0 && (actuallyHasTldrContent || actuallyHasVisualContent)) {
        // No model details but has meaningful TLDR = show tabs (Main + TLDR)
        // But NOT during live streaming - wait until streaming ends
        if (!isLiveStreaming) {
            shouldBuildTabs = true;
        }
    }

    if (!isLiveStreaming) {
        // [DEBUG] console.warn('[applyModelResponseTabs] shouldBuildTabs:', shouldBuildTabs, '| models:', modelDetails.length, '| actuallyHasTldrContent:', actuallyHasTldrContent, '| actuallyHasVisualContent:', actuallyHasVisualContent, '| isLiveStreaming:', isLiveStreaming);
    }
    if (!shouldBuildTabs) {
        if ($existingContainer.length > 0) {
            $existingContainer.remove();
        }
        $root.removeAttr('data-has-tabs');
        $root.find('[data-model-tabs-hidden="true"]').show().removeAttr('data-model-tabs-hidden');
        return;
    }
    
    // ========================================================================
    // STEP 3: Create/update tab container
    // ========================================================================
    if (!$existingContainer.length) {
        $container.attr('data-model-tab-group', groupKey);
        $container.append('<ul class="nav nav-tabs" id="' + navId + '" role="tablist"></ul>');
        $container.append('<div class="tab-content" id="' + contentId + '"></div>');
    } else {
        $container.find('.nav').empty();
        $container.find('.tab-content').empty();
    }

    var $nav = $container.find('.nav');
    var $content = $container.find('.tab-content');

    // In chat UI, we treat `.chat-card-body` as the stable host for tabs.
    // The ToC UI is also hosted there (outside showMore()), and sibling hiding can
    // reliably remove duplicate render containers.
    var $tabsHostPreferred = $root;
    
    // ========================================================================
    // STEP 4: Build tab items using validated TLDR status
    // ========================================================================
    var tabItems = [];
    if (modelDetails.length > 0) {
        // Only consider it a "single model with TLDR" if TLDR actually has meaningful content
        var singleModel = modelDetails.length === 1 && (actuallyHasTldrContent || actuallyHasVisualContent);
        modelDetails.forEach(function(item, idx) {
            var label = item.summary.replace(/^Response from\s*/i, '').trim();
            if (singleModel) {
                label = 'Main';
            } else if (!label) {
                label = 'Response';
            }
            tabItems.push({
                key: 'model-' + idx + '-' + label.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, ''),
                label: label,
                element: item.element,
                type: 'model'
            });
        });
    } else if (actuallyHasTldrContent || actuallyHasVisualContent) {
        // No model details but we have TLDR or Visual - add a "Main" tab for the content
        tabItems.push({
            key: 'main',
            label: 'Main',
            element: null,
            type: 'main'
        });
    }

    // Add TLDR tab only if we have validated meaningful content
    if (actuallyHasTldrContent) {
        tabItems.push({
            key: 'tldr',
            label: 'TLDR',
            element: tldrDetails.length > 0 ? tldrDetails[0].element : null,
            type: 'tldr'
        });
    }

    // Add Visual tab if present
    if (actuallyHasVisualContent) {
        tabItems.push({
            key: 'visual',
            label: '🎨 Visual',
            element: hasVisualWrapper ? $visualWrapper : (visualDetails.length > 0 ? visualDetails[0].element : null),
            type: 'visual'
        });
    }

    // Add Diff tab if multiple models present (before TLDR/Visual — splice it in)
    var $diffBlocks = $root.find('[data-answer-diff]');
    var hasDiffContent = $diffBlocks.length > 0;
    var isMultiModel = modelDetails.length > 1;
    if (isMultiModel) {
        // Insert diff right after model tabs (before tldr/visual)
        var diffInsertIdx = modelDetails.length > 0 ? modelDetails.length : 0;
        tabItems.splice(diffInsertIdx, 0, {
            key: 'diff',
            label: '⚡ Diff',
            element: null,
            type: 'diff'
        });
    }

    tabItems.forEach(function(item, itemIndex) {
        var tabKey = item.key;
        var tabId = groupKey + '-tab-' + tabKey;
        var paneId = groupKey + '-pane-' + tabKey;
        var isActive = false;
        if (activeTabKey && activeTabKey === tabKey) {
            isActive = true;
        } else if (!activeTabKey && itemIndex === 0) {
            isActive = true;
        }

        var $navItem = $('<li class="nav-item" role="presentation"></li>');
        var $navLink = $('<a class="nav-link" data-toggle="tab" role="tab" aria-controls="' + paneId + '" aria-selected="false"></a>');
        $navLink.attr('href', '#' + paneId);
        $navLink.attr('data-tab-key', tabKey);
        $navLink.text(item.label);
        if (isActive) {
            $navLink.addClass('active');
            $navLink.attr('aria-selected', 'true');
        }
        $navItem.append($navLink);
        $nav.append($navItem);

        var $pane = $('<div class="tab-pane fade" role="tabpanel"></div>');
        $pane.attr('id', paneId);
        if (isActive) {
            $pane.addClass('show active');
        }

        var $body = $('<div class="model-tab-body"></div>');
        if (item.type === 'tldr') {
            if (tldrContentClone) {
                if (tldrContentClone.is('details')) {
                    tldrContentClone.removeAttr('open');
                    tldrContentClone.find('> summary').first().remove();
                    restoreHiddenForClone(tldrContentClone);
                    $body.append(tldrContentClone.contents());
                } else {
                    restoreHiddenForClone(tldrContentClone);
                    $body.append(tldrContentClone.contents());
                }
            }
        } else if (item.type === 'diff') {
            // Build diff tab content from <answer_diff> blocks
            if (hasDiffContent) {
                var $diffContainer = $('<div class="diff-tab-content"></div>');
                var allAgree = true;
                $diffBlocks.each(function() {
                    var $block = $(this);
                    var diffModel = $block.attr('data-diff-model') || '';
                    var rawJson = ($block.text() || '').trim();
                    try {
                        var diffData = JSON.parse(rawJson);
                        var stats = diffData.stats || {};
                        if ((stats.additions || 0) + (stats.contradictions || 0) + (stats.omissions || 0) > 0) {
                            allAgree = false;
                        }
                        var badge = diffData.badge_summary || '';
                        // Build model group
                        var $group = $('<div class="diff-model-group"></div>');
                        var shortName = diffModel.replace(/^.*\//, '');
                        $group.append('<h6 class="diff-model-header">vs ' + shortName + (badge ? ' <span class="model-diff-badge">' + badge + '</span>' : '') + '</h6>');
                        var sections = diffData.diff_sections || [];
                        for (var si = 0; si < sections.length; si++) {
                            var sec = sections[si];
                            var icon = sec.type === 'addition' ? '✅' : sec.type === 'contradiction' ? '⚠️' : '❌';
                            var typeClass = 'diff-' + sec.type;
                            var $sec = $('<div class="diff-section ' + typeClass + '"></div>');
                            $sec.append('<div class="diff-section-header">' + icon + ' ' + (sec.topic || '') + '</div>');
                            var detailHtml = (typeof marked !== 'undefined' && marked.parse) ? marked.parse(sec.detail || '') : (sec.detail || '');
                            $sec.append('<div class="diff-section-body">' + detailHtml + '</div>');
                            $group.append($sec);
                        }
                        if (sections.length > 0) $diffContainer.append($group);
                        // Inject badge into the corresponding model tab nav-link
                        if (badge) {
                            var shortNameLower = shortName.toLowerCase();
                            $nav.find('.nav-link').each(function() {
                                var $link = $(this);
                                var tabKey = ($link.attr('data-tab-key') || '').toLowerCase();
                                var linkText = ($link.text() || '').trim().toLowerCase();
                                // Match by checking if the model short name appears in the tab key or label
                                if ((tabKey.indexOf(shortNameLower) !== -1 || linkText.indexOf(shortNameLower) !== -1) && tabKey !== 'diff' && tabKey !== 'tldr' && tabKey !== 'visual') {
                                    if (!$link.find('.model-diff-badge').length) {
                                        $link.append(' <span class="model-diff-badge">' + badge + '</span>');
                                    }
                                }
                            });
                        }
                    } catch (e) { /* ignore parse errors */ }
                    $block.attr('data-model-tabs-hidden', 'true');
                    $block[0].style.display = 'none';
                });
                if (allAgree) {
                    $diffContainer.append('<div class="diff-all-agree">✅ All models agree</div>');
                } else if ($diffContainer.find('.diff-model-group').length === 0) {
                    // Stats indicated differences but no sections rendered — show generic message
                    $diffContainer.append('<div class="diff-all-agree">✅ All models agree</div>');
                }
                $body.append($diffContainer);
            } else if (isLiveStreaming || (!hasDiffContent && isMultiModel)) {
                // Show spinner while waiting for diff results
                $body.append('<div class="diff-loading-spinner"><span class="spinner-border spinner-border-sm"></span> Generating comparison...</div>');
            }
        } else if (item.type === 'main') {
            // For the single-model case we want the full rendered message content.
            // After showMore() runs, the real content usually lives inside `.more-text`.
            // Prefer that as the source so we don't accidentally clone the collapsed wrapper.
            var $contentRoot = $root.find('.more-text').first();
            if ($contentRoot.length === 0) {
                $contentRoot = $root.find('.actual-card-text').last();
            }
            var $mainClone = ($contentRoot.length > 0 ? $contentRoot : $root).clone(true, true);

            // Prevent recursive/duplicated content: never include tab UIs inside panes.
            $mainClone.find('.model-tabs-container').remove();
            // Don't show the showMore toggle inside the tab pane.
            $mainClone.find('a.show-more').remove();
            $mainClone.find('[data-answer-tldr]').remove();
            $mainClone.find('[data-answer-diff]').remove();
            // Remove visual wrapper and its parent section-details
            $mainClone.find('[data-answer-visual]').each(function() {
                var $parentSection = $(this).closest('.section-details');
                if ($parentSection.length > 0) {
                    $parentSection.remove();
                } else {
                    $(this).remove();
                }
            });
            $mainClone.find('details').each(function() {
                var $details = $(this);
                var summaryText = ($details.find('> summary').first().text() || '').trim().toLowerCase();
                if (summaryText.indexOf('tldr') !== -1 || summaryText.indexOf('tldr summary') !== -1 || summaryText.indexOf('visual explanation') !== -1 || summaryText.indexOf('🎨') !== -1) {
                    $details.remove();
                }
            });
            restoreHiddenForClone($mainClone);
            $body.append($mainClone.contents());
        } else if (item.element) {
            var $detailsClone = item.element.clone(true, true);
            $detailsClone.removeAttr('open');
            $detailsClone.find('> summary').first().remove();
            // Same as above: cloned model details can contain an existing tabs container.
            $detailsClone.find('.model-tabs-container').remove();
            $detailsClone.find('[data-answer-tldr]').remove();
            $detailsClone.find('[data-answer-visual]').remove();
            $detailsClone.find('[data-answer-diff]').remove();
            $detailsClone.find('details').each(function() {
                var $details = $(this);
                var summaryText = ($details.find('> summary').first().text() || '').trim().toLowerCase();
                if (summaryText.indexOf('tldr') !== -1 || summaryText.indexOf('tldr summary') !== -1) {
                    $details.remove();
                }
            });
            restoreHiddenForClone($detailsClone);
            $body.append($detailsClone.contents());
        }

        $pane.append($body);
        $content.append($pane);
    });

    // ========================================================================
    // DOM SWAP: Insert tabs + hide originals
    // ========================================================================
    // SCROLL PREVENTION via HEIGHT LOCK:
    // When we hide all children then insert the tab container, the card body's height
    // momentarily drops to ~0 (all children hidden) before growing back (tabs inserted).
    // This height collapse causes the browser to shift scrollTop — visible as a "scroll up
    // then back down" jank. To prevent this, we lock the container's min-height to its
    // current rendered height BEFORE any DOM changes, then release AFTER all changes.
    // The scroll position never shifts because the total page height stays constant.
    var _heightLockEl = $root[0];
    var _heightLockValue = 0;
    try {
        if (_heightLockEl) {
            _heightLockValue = _heightLockEl.offsetHeight || 0;
            if (_heightLockValue > 0) {
                _heightLockEl.style.minHeight = _heightLockValue + 'px';
            }
        }
    } catch (e) { /* ignore */ }
    
    // --- Step A: Hide originals FIRST (using css directly to avoid forced reflows) ---
    // By hiding originals before inserting tabs, we avoid the "content pushed down then
    // pulled back up" problem. The originals disappear, then tabs fill the same space.
    var $hideHost = $tabsHostPreferred;
    try {
        if (!($hideHost && $hideHost.length)) {
            $hideHost = $root;
        }
        if ($hideHost && $hideHost.length > 0) {
            $hideHost.children()
                .not('.model-tabs-container')
                .not('.message-toc-container')
                .each(function() {
                    $(this).attr('data-model-tabs-hidden', 'true');
                    this.style.display = 'none';  // Direct style access avoids jQuery overhead
                });
        }
    } catch (e) { /* ignore */ }

    modelDetails.forEach(function(item) {
        item.element.attr('data-model-tabs-hidden', 'true');
        if (item.element[0]) item.element[0].style.display = 'none';
    });

    // --- Step B: Insert/move the tab container ---
    if ($existingContainer.length === 0) {
        // Insert tabs at the top-level of the preferred host so they are not trapped
        // inside section <details> wrappers (common when answers are split by `---`).
        var $insertHost = $tabsHostPreferred;
        if ($insertHost && $insertHost.length && $insertHost[0] !== document) {
            $insertHost.prepend($container);
        } else if ($detailsBlocks.length > 0) {
            $detailsBlocks.first().before($container);
        } else {
            $root.prepend($container);
        }
    } else {
        // Re-apply scenario: ensure the container lives under the preferred host.
        try {
            if ($tabsHostPreferred && $tabsHostPreferred.length && $container.parent().length && $container.parent()[0] !== $tabsHostPreferred[0]) {
                $tabsHostPreferred.prepend($container);
            }
        } catch (e) { /* ignore */ }
    }
    
    // Ensure the container is within the hide host so children() covers the sources.
    try {
        if ($hideHost && $hideHost.length > 0 && $container.parent().length && $container.parent()[0] !== $hideHost[0]) {
            $hideHost.prepend($container);
        }
    } catch (e) { /* ignore */ }

    // If the tab UI isn't actually attached, don't hide sources.
    // This prevents the "ToC shows but content is blank" state on reload.
    try {
        if (!$container || $container.length === 0 || !$container[0] || !document.body.contains($container[0])) {
            $root.removeAttr('data-has-tabs');
            $root.find('[data-model-tabs-hidden="true"]').show().removeAttr('data-model-tabs-hidden');
            // Release height lock before early exit
            try { if (_heightLockEl && _heightLockValue > 0) _heightLockEl.style.minHeight = ''; } catch (e2) {}
            return;
        }
    } catch (e) { /* ignore */ }

    // --- Step C: Remove TLDR sources (only after content is cloned into tabs) ---
    if (actuallyHasTldrContent) {
        if (hasTldrWrapper && $tldrWrapper.length > 0) {
            $tldrWrapper.remove();
        }
        tldrDetails.forEach(function(item) {
            item.element.remove();
        });
        // Defensive: if we accidentally inserted tabs inside the TLDR wrapper,
        // removing the wrapper would also remove the tabs container.
        try {
            if ($container && $container.length > 0 && $container[0] && !document.body.contains($container[0])) {
                $root.prepend($container);
            }
        } catch (e) { /* ignore */ }
    }

    // Hide visual source (content is now in the Visual tab)
    if (actuallyHasVisualContent) {
        // [DEBUG] console.warn('[applyModelResponseTabs] HIDING visual source | visualDetails:', visualDetails.length, '| hasVisualWrapper:', hasVisualWrapper, '| $visualWrapper.length:', $visualWrapper.length);
        visualDetails.forEach(function(item) { item.element.attr('data-model-tabs-hidden', 'true'); item.element[0].style.display = 'none'; });
        if (hasVisualWrapper && $visualWrapper.length > 0) {
            $visualWrapper.attr('data-model-tabs-hidden', 'true');
            $visualWrapper[0].style.display = 'none';
        }
    }

    if (scrollTop) {
        $content.scrollTop(scrollTop);
    }

    // Final sanity check: never leave a message blank.
    // Also stamp data-has-tabs on $root so callers can gate on an O(1) attribute
    // check instead of a DOM traversal for .model-tabs-container.
    try {
        var hasTabsInRoot = $root.find('.model-tabs-container').length > 0;
        if (hasTabsInRoot) {
            $root.attr('data-has-tabs', '1');
        } else {
            $root.removeAttr('data-has-tabs');
            $root.find('[data-model-tabs-hidden="true"]').show().removeAttr('data-model-tabs-hidden');
        }
    } catch (e) { /* ignore */ }
    
    // RELEASE HEIGHT LOCK: All DOM changes (hide, insert, remove) are done.
    // The tab container is now visible with content. Release the min-height lock
    // so the card body settles to its natural height. Any small height difference
    // between the locked height and the natural height is handled by CSS scroll
    // anchoring (overflow-anchor: auto).
    try {
        if (_heightLockEl && _heightLockValue > 0) {
            _heightLockEl.style.minHeight = '';
        }
    } catch (e) { /* ignore */ }

    // Render mermaid diagrams when a tab becomes visible (mermaid needs visible DOM)
    try {
        $container.off('shown.bs.tab').on('shown.bs.tab', function(e) {
            var $pane = $($(e.target).attr('href'));
            // Delay slightly to ensure pane is fully visible (fade transition)
            setTimeout(function() {
                // Reset failed mermaid blocks so they can be re-rendered now that the pane is visible
                $pane.find('pre.mermaid[data-mermaid-failed]').each(function() {
                    this.removeAttribute('data-mermaid-failed');
                    $(this).next('button').remove(); // remove fix button
                    $(this).css({ 'font-size': '', 'opacity': '', 'white-space': '' });
                });
                // Also reset blocks with error SVGs
                $pane.find('pre.mermaid').has('svg').each(function() {
                    var svg = this.querySelector('svg');
                    var isError = svg && (svg.querySelector('.error-text') ||
                        (svg.textContent || '').indexOf('Syntax error') !== -1);
                    if (isError) {
                        var src = this.getAttribute('data-mermaid-source') || '';
                        if (src) { $(this).empty().text(src); }
                    }
                });
                if (typeof renderMermaidIn === 'function') renderMermaidIn($pane);
            }, 200);
        });
        // Also render in the currently active pane
        var $activePane = $container.find('.tab-pane.show.active').first();
        if ($activePane.length && typeof renderMermaidIn === 'function') renderMermaidIn($activePane);
    } catch (e) { /* ignore */ }

    // Ensure the collapse [show]/[hide] toggle exists for tabbed answers and re-apply
    // any persisted collapsed state. Called on every (re)render so streaming rebuilds
    // (which empty the nav) keep the toggle and its state intact.
    try { ensureTabsAnswerToggle($container); } catch (e) { /* ignore */ }
}

// ============================================================================
// Tabbed-answer collapse [show]/[hide] toggle
// ----------------------------------------------------------------------------
// When a response renders as model tabs (.model-tabs-container), the original
// showMore() [show]/[hide] toggle is unavailable: its host (#message-render-space)
// is force-hidden (both via JS data-model-tabs-hidden and the CSS :has() rule in
// interface.html), and the cloned tab content has `a.show-more` stripped out.
// These helpers add an equivalent collapse control that hides the tab CONTENT
// (.tab-content) while keeping the nav bar (and toggle) visible, and persist the
// state via the SAME /show_hide_message_from_conversation backend used by
// showMore() — so the collapsed/expanded choice is remembered across sessions.
// ============================================================================

/**
 * Resolve {conversationId, messageId} for a tabs container.
 * Returns empty strings when not resolvable (e.g. doubt / temp-llm cards), in
 * which case persistence is skipped but the local toggle still works.
 *
 * @param {jQuery} $container - .model-tabs-container
 * @returns {{conversationId: string, messageId: string}}
 */
function getTabsAnswerIds($container) {
    var conversationId = '';
    try {
        if (typeof ConversationManager !== 'undefined' && ConversationManager) {
            conversationId = ConversationManager.activeConversationId ||
                (ConversationManager.getActiveConversation ? ConversationManager.getActiveConversation() : '') || '';
        }
    } catch (e) { /* ignore */ }
    var messageId = '';
    try {
        var $card = $container.closest('.card.message-card');
        if ($card.length) {
            messageId = $card.find('.card-header[message-id]').first().attr('message-id') || '';
        }
    } catch (e) { /* ignore */ }
    return { conversationId: conversationId, messageId: messageId };
}

/**
 * Apply collapsed/expanded visual state to a tabs container.
 * collapsed => hide .tab-content (nav + toggle stay visible), toggles read "[show]".
 * expanded  => show .tab-content, toggles read "[hide]".
 * The state is stored on the container via data-answer-collapsed so streaming
 * re-renders (which rebuild the nav/content) can re-apply it.
 *
 * @param {jQuery} $container - .model-tabs-container
 * @param {boolean} collapsed
 */
function applyTabsCollapsedState($container, collapsed) {
    if (!$container || !$container.length) return;
    var $content = $container.find('> .tab-content').first();
    if (!$content.length) $content = $container.find('.tab-content').first();
    if (collapsed) {
        if ($content.length) $content[0].style.display = 'none';
        $container.attr('data-answer-collapsed', 'true');
    } else {
        if ($content.length) $content[0].style.display = '';
        $container.removeAttr('data-answer-collapsed');
    }
    var label = collapsed ? '[show]' : '[hide]';
    $container.find('.model-tabs-collapse-toggle').text(label);
    var $card = $container.closest('.card');
    if ($card.length) {
        $card.find('.model-tabs-collapse-toggle-bottom').text(label);
    }
}

/**
 * Position the bottom collapse toggle just to the LEFT of the scroll-to-top
 * button. The scroll-to-top button is absolutely positioned at right:5px, so the
 * toggle's right offset must clear the button's full measured width PLUS that 5px
 * base, plus a small gap. Measured each call because the scroll button may be
 * appended AFTER the toggle in the same render tick.
 *
 * @param {jQuery} $card - the .card containing both controls
 */
function positionTabsBottomToggle($card) {
    if (!$card || !$card.length) return;
    var $btn = $card.find('> .model-tabs-collapse-toggle-bottom').first();
    if (!$btn.length) return;
    var $scrollBtn = $card.find('> .scroll-to-top-btn').first();
    // Fallback (used only momentarily before the scroll button exists/measures);
    // generous enough to clear the "Top ↑" button.
    var rightOffset = 150;
    if ($scrollBtn.length) {
        // 5px = scroll button's own right offset; +10px gap between the two.
        rightOffset = 5 + ($scrollBtn.outerWidth(true) || 120) + 10;
    }
    $btn.css('right', rightOffset + 'px');

    // Doubt-modal ingress sits just to the LEFT of the show/hide toggle, so the
    // bottom row reads (right -> left): [scroll-to-top] [show/hide] [doubts].
    var $doubt = $card.find('> .model-tabs-doubt-ingress-bottom').first();
    if ($doubt.length) {
        $doubt.css('right', (rightOffset + ($btn.outerWidth(true) || 50) + 8) + 'px');
    }
}

/**
 * Idempotently inject the collapse toggles for a tabs container and re-apply the
 * persisted collapsed state. Safe to call on every render.
 *
 * Top toggle:    an `ml-auto` <li> at the right edge of the .nav-tabs ul (above
 *                the per-pane ToC). Re-injected when missing, because the nav is
 *                emptied/rebuilt on streaming re-renders.
 * Bottom toggle: a button on the card, positioned just left of the
 *                scroll-to-top (".scroll-to-top-btn") button.
 *
 * @param {jQuery} $container - .model-tabs-container
 */
function ensureTabsAnswerToggle($container) {
    if (!$container || !$container.length) return;
    var $nav = $container.find('> .nav').first();
    if (!$nav.length) $nav = $container.find('.nav').first();
    if (!$nav.length) return;

    // --- Top toggle (right side of the nav-tabs ul) ---
    if (!$nav.find('.model-tabs-collapse-li').length) {
        var $li = $('<li class="nav-item model-tabs-collapse-li ml-auto"></li>');
        var $a = $('<a href="#" class="model-tabs-collapse-toggle" title="Collapse / expand this answer">[hide]</a>');
        $li.append($a);
        $nav.append($li);
    }

    // --- Bottom toggle (left of the scroll-to-top button) ---
    var $card = $container.closest('.card');
    if ($card.length) {
        if (($card.css('position') || 'static') === 'static') {
            $card.css('position', 'relative');
        }
        if (!$card.find('> .model-tabs-collapse-toggle-bottom').length) {
            var $btn = $('<button type="button" class="model-tabs-collapse-toggle-bottom" title="Collapse / expand this answer">[hide]</button>');
            $card.append($btn);
        }
        // Doubt-modal ingress, mirroring the header's doubts button. Sits to the left
        // of the bottom show/hide toggle and opens the doubts overview for this
        // message. The message_id is read from the card header at click time (it may
        // be a placeholder until a freshly-streamed message is assigned its real id).
        if (!$card.find('> .model-tabs-doubt-ingress-bottom').length) {
            var $doubtBtn = $('<button type="button" class="model-tabs-doubt-ingress-bottom" title="View / ask doubts"><i class="bi bi-chat-left-text"></i></button>');
            $card.append($doubtBtn);
        }
        // (Re)position relative to the scroll-to-top button. Do it now AND on the
        // next frame: the scroll-to-top button is frequently appended AFTER this
        // runs in the same render tick, so the synchronous pass may not see it yet
        // and would fall back to the default offset (causing the toggle to overlay
        // the button). The rAF pass runs before paint, so it never visibly overlaps.
        positionTabsBottomToggle($card);
        requestAnimationFrame(function() { positionTabsBottomToggle($card); });
    }

    // Re-apply persisted collapsed state (data-answer-collapsed survives re-renders).
    var collapsed = $container.attr('data-answer-collapsed') === 'true';
    applyTabsCollapsedState($container, collapsed);
}

// Delegated handler — survives DOM rebuilds (applyModelResponseTabs re-renders and
// RenderedStateManager snapshot restores). Toggles the collapse state and persists
// via the same per-message backend used by showMore().
$(document).on('click', '.model-tabs-collapse-toggle, .model-tabs-collapse-toggle-bottom', function(e) {
    e.preventDefault();
    e.stopPropagation();
    // Top toggle lives inside the container; bottom toggle is a sibling of the
    // card body, so fall back to a card-scoped lookup for it.
    var $container = $(this).closest('.model-tabs-container');
    if (!$container.length) {
        $container = $(this).closest('.card').find('.model-tabs-container').first();
    }
    if (!$container.length) return;

    var nowCollapsed = !($container.attr('data-answer-collapsed') === 'true');
    applyTabsCollapsedState($container, nowCollapsed);

    // Persist (best-effort) using the existing /show_hide_message_from_conversation API.
    var ids = getTabsAnswerIds($container);
    if (ids.conversationId && ids.messageId) {
        var show_hide = nowCollapsed ? 'hide' : 'show';
        if (window.ConversationUIState) {
            window.ConversationUIState.updateMessage(ids.conversationId, ids.messageId, show_hide);
        }
        apiCall('/show_hide_message_from_conversation/' + ids.conversationId + '/' + ids.messageId + '/0',
            'POST', { 'show_hide': show_hide })
            .fail(function(xhr, status, error) {
                console.error('Failed to save tabbed show/hide state:', (xhr && xhr.responseJSON && xhr.responseJSON.message) || error || 'Unknown error');
            });
    }
});

// Delegated handler — bottom doubt-modal ingress on tabbed answer cards. Mirrors
// the header doubts button: opens the doubts overview for this message. The
// message id is read from the card header at click time (it may be a placeholder
// until a freshly-streamed message is assigned its real id).
$(document).on('click', '.model-tabs-doubt-ingress-bottom', function(e) {
    e.preventDefault();
    e.stopPropagation();
    var $card = $(this).closest('.card.message-card');
    if (!$card.length) $card = $(this).closest('.card');
    var messageId = $card.find('.card-header[message-id]').attr('message-id');
    var conversationId = (typeof ConversationManager !== 'undefined' && ConversationManager.activeConversationId)
        ? ConversationManager.activeConversationId : null;
    if (conversationId && messageId && messageId !== 'undefined' && typeof DoubtManager !== 'undefined') {
        DoubtManager.showDoubtsOverview(conversationId, messageId);
    }
});

// Function to attach listeners for section <details>/<summary> toggles.
//
// The native <details> `toggle` event does NOT bubble, so it cannot be
// delegated. Instead we delegate the summary CLICK on `document` (mirroring the
// `.close-section-btn` handler) and read the post-toggle open state on the next
// tick. Binding on `document` — rather than on the per-render `elem_to_render_in`
// — is essential: it ensures the handler also fires for sections that live
// OUTSIDE that element, e.g. the section clones placed inside a
// `.model-tabs-container` tab pane, and snapshot-restored cards. Previously the
// handler was bound on `elem_to_render_in`, so toggling such sections via the
// summary never reached it and the state was never persisted (only the
// document-delegated "Close Section" button worked). A namespaced off/on keeps
// the binding idempotent across repeated render calls.
// One-time delegated handler for section <details>/<summary> toggle persistence.
// The native <details> `toggle` event does NOT bubble, so it cannot be delegated.
// Instead we delegate the summary CLICK on `document` (mirroring the
// `.close-section-btn` handler directly below) and read the post-toggle open
// state on the next tick via setTimeout(0).
//
// Binding on `document` — rather than on a per-render element — is essential: it
// fires for sections that live outside the per-render element, e.g. clones placed
// inside a `.model-tabs-container` tab pane and snapshot-restored cards.
//
// Previously this was wrapped in `attachSectionListeners(elem)` and called on
// every final render (once per message during history load). The function never
// used its `elem` argument — the handler was always bound on `document`. Moving
// it here registers it exactly once at module load, identical in behaviour but
// without the per-render overhead.
$(document)
    .off('click.sectionToggle', '.section-details > summary')
    .on('click.sectionToggle', '.section-details > summary', function() {
        var $section = $(this).closest('.section-details');
        if (!$section.length) return;
        var sectionHash = $section.attr('data-section-hash');
        // Read the open state AFTER the browser applies the native toggle.
        setTimeout(function() {
            var isHidden = !$section.prop('open');
            var convId = (typeof ConversationManager !== 'undefined' && ConversationManager && ConversationManager.getActiveConversation() != '') ? ConversationManager.getActiveConversation() : '';
            if (convId && sectionHash) {
                persistSectionState(convId, sectionHash, isHidden);
            }
        }, 0);
    });

// One-time delegated handler for the "Close Section" button inside section <details> blocks.
// Registered here at module load rather than inside renderInnerContentAsMarkdown so it is
// set up exactly once. The handler reads `conversation_id` at click time — that variable is
// a module-level global written by renderInnerContentAsMarkdown on every render, so it
// always holds the current active conversation regardless of when this handler was registered.
$(document).on('click', '.close-section-btn', function(e) {
    e.preventDefault();
    e.stopPropagation();

    var sectionId = $(this).data('section-id');
    var detailsElement = $(document.getElementById(sectionId));

    if (detailsElement.length) {
        var sectionHash = detailsElement.attr('data-section-hash');

        // Close the details element
        detailsElement.prop('open', false);

        // Programmatic changes don't fire the toggle event, so persist state manually
        if (conversation_id && sectionHash) {
            persistSectionState(conversation_id, sectionHash, true); // true = hidden
        }

        // Smooth scroll to the summary
        detailsElement[0].scrollIntoView({
            behavior: 'smooth',
            block: 'nearest'
        });
    }
});


// Helper function to generate a summary for each section
function generateSectionSummary(sectionContent, sectionIndex) {
    /**
     * Generate a summary title for a section based on its content
     * 
     * @param {string} sectionContent - The markdown content of the section
     * @param {number} sectionIndex - The index of the section (0-based)
     * @returns {string} - A summary title for the section
     */
    
    // Try to extract the first heading if it exists
    var headingMatch = sectionContent.match(/^#{1,6}\s+(.+?)$/m);
    if (headingMatch) {
        return headingMatch[1].trim();
    }
    
    // Try to get the first line of text (non-empty, non-code)
    var lines = sectionContent.split('\n');
    for (var line of lines) {
        line = line.trim();
        line = line.replace(/<answer>/g, '').replace(/<\/answer>/g, '').replace(/\*/g, '');
        // Skip empty lines, code blocks, and special markdown syntax
        if (line && !line.startsWith('```') && !line.startsWith('    ') && !line.startsWith('\t')) {
            // Truncate if too long and add ellipsis
            if (line.length > 50) {
                return line.substring(0, 47) + '...';
            }
            return line;
        }
    }
    
    // Default fallback
    return `Section ${sectionIndex + 1}\n`;
}

// Add this helper function to handle closing sections
function closeSectionDetails(sectionId) {
    /**
     * Close a specific section details element and persist state
     * 
     * @param {string} sectionId - The ID of the details element to close
     */
    var detailsElement = document.getElementById(sectionId);
    if (detailsElement) {
        var $details = $(detailsElement);
        var sectionHash = $details.attr('data-section-hash');
        
        detailsElement.removeAttribute('open');
        
        // Persist the hidden state
        var convId = (typeof ConversationManager !== 'undefined' && ConversationManager && ConversationManager.getActiveConversation() != '') ? ConversationManager.getActiveConversation() : '';
        if (convId && sectionHash) {
            persistSectionState(convId, sectionHash, true);
        }
        
        // Scroll to the summary so it's visible after closing
        detailsElement.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
}

// Helper function to fetch and apply section hidden states
function fetchAndApplySectionStates(conversation_id, elem_to_render_in) {
    // Find all section-details elements
    const sectionElements = $(elem_to_render_in).find('.section-details');
    if (sectionElements.length === 0) return;
    
    // If mocking is enabled, just hide all sections by default and skip API call
    if (MOCK_SECTION_STATE_API) {
        sectionElements.each(function() {
            $(this).prop('open', true);
        });
        return;
    }
    
    // Collect section IDs
    const sectionIds = [];
    sectionElements.each(function() {
        // Use data-section-hash (the persist key) so it matches stored records.
        var sectionKey = $(this).attr('data-section-hash') || ($(this).attr('id') || '').replace(/^section-details-/, '');
        if (sectionKey) {
            sectionIds.push(sectionKey);
        }
    });
    
    if (sectionIds.length === 0) return;
    
    // Fetch hidden states from server
    $.ajax({
        url: '/get_section_hidden_details',
        method: 'GET',
        data: {
            conversation_id: conversation_id,
            section_ids: sectionIds.join(',')
        },
        success: function(response) {
            if (response && response.section_details) {
                // Apply the states to the details elements
                sectionElements.each(function() {
                    const sectionElement = $(this);
                    var sectionKey = sectionElement.attr('data-section-hash') || (sectionElement.attr('id') || '').replace(/^section-details-/, '');
                    const sectionData = sectionKey ? response.section_details[sectionKey] : undefined;
                    if (sectionData && sectionData.hidden) {
                        // Close the section if it's marked as hidden
                        sectionElement.prop('open', false);
                    }
                });
            }
        },
        error: function(xhr, status, error) {
            console.error('Failed to fetch section hidden states:', error);
        }
    });
}

// ============================================================================
// Conversation UI-state cache
// ----------------------------------------------------------------------------
// Section-collapse states + per-message show/hide are needed to render a
// conversation in its FINAL state. To avoid a second backend round trip (and a
// second full conversation load on the server), this state is folded into the
// /list_messages_by_conversation?include_ui_state=true response and stashed
// here. Render-time code reads it to paint sections/answers already collapsed
// (no expand-then-collapse flash), and fetchConversationUIState() reads it
// instead of hitting the network. User toggles keep it fresh so it stays
// authoritative for the whole session.
// ============================================================================
window.ConversationUIState = window.ConversationUIState || {
    _cache: {},
    _lastUsed: {},
    _appliedTo: {},
    MAX_ENTRIES: 30,

    /** Mark a conversation as recently used and evict the oldest if over cap. */
    _touch: function(convId) {
        if (!convId) return;
        this._lastUsed[convId] = Date.now();
        var keys = Object.keys(this._cache);
        if (keys.length <= this.MAX_ENTRIES) return;
        var oldestKey = null;
        var oldestTime = Infinity;
        for (var i = 0; i < keys.length; i++) {
            var k = keys[i];
            var t = this._lastUsed[k] || 0;
            if (t < oldestTime) {
                oldestTime = t;
                oldestKey = k;
            }
        }
        if (oldestKey) {
            delete this._cache[oldestKey];
            delete this._lastUsed[oldestKey];
        }
    },

    /** Empty the cache entirely (call on logout). */
    clear: function() {
        this._cache = {};
        this._lastUsed = {};
        this._appliedTo = {};
    },

    /** Mark that applyConversationUIState already ran synchronously for this render pass. */
    markApplied: function(convId) {
        if (convId) { this._appliedTo[convId] = true; }
    },
    isApplied: function(convId) {
        return !!(convId && this._appliedTo[convId]);
    },
    clearApplied: function(convId) {
        if (convId) { delete this._appliedTo[convId]; }
    },

    /** Populate from a list_messages payload: per-message show_hide + section map. */
    setFromList: function(convId, msgList, sectionDetails) {
        if (!convId) return;
        var messageShowHide = {};
        (msgList || []).forEach(function(m) {
            if (m && m.message_id) { messageShowHide[m.message_id] = m.show_hide || 'show'; }
        });
        this._cache[convId] = { section_details: sectionDetails || {}, message_show_hide: messageShowHide };
        this._touch(convId);
    },
    /** Populate from an explicit {section_details, message_show_hide} (network shape). */
    set: function(convId, sectionDetails, messageShowHide) {
        if (!convId) return;
        this._cache[convId] = { section_details: sectionDetails || {}, message_show_hide: messageShowHide || {} };
        this._touch(convId);
    },
    has: function(convId) { return !!(convId && this._cache[convId]); },
    get: function(convId) {
        if (!convId || !this._cache[convId]) return undefined;
        this._touch(convId);
        return this._cache[convId];
    },
    updateSection: function(convId, sectionHash, hidden) {
        if (!convId || !sectionHash) return;
        var e = this._cache[convId] || (this._cache[convId] = { section_details: {}, message_show_hide: {} });
        e.section_details[sectionHash] = { hidden: !!hidden };
        this._touch(convId);
    },
    updateMessage: function(convId, messageId, showHide) {
        if (!convId || !messageId) return;
        var e = this._cache[convId] || (this._cache[convId] = { section_details: {}, message_show_hide: {} });
        e.message_show_hide[messageId] = showHide;
        this._touch(convId);
    }
};

/**
 * Apply conversation UI state (section collapse + message show/hide) to the DOM.
 * Pure DOM work — no network. Shared by the render-time path, the snapshot-restore
 * path, and fetchConversationUIState (cache or network).
 *
 * @param {Object} section_details   — { data-section-hash : {hidden: bool} }
 * @param {Object} message_show_hide — { message_id : 'show' | 'hide' }
 * @param {HTMLElement|jQuery} elem_to_render_in
 */
function applyConversationUIState(section_details, message_show_hide, elem_to_render_in) {
    var $container = $(elem_to_render_in);

    // --- Section collapse states ---
    if (section_details) {
        $container.find('.section-details').each(function() {
            var $el = $(this);
            // Key MUST match the persist key = data-section-hash (see persistSectionState
            // and friends). The id-derived value only coincidentally matches for
            // top-level sections; nested sections persist a bare hash.
            var sectionKey = $el.attr('data-section-hash');
            var data = sectionKey ? section_details[sectionKey] : undefined;
            if (!data) {
                var sectionId = $el.attr('id');
                if (sectionId) { data = section_details[sectionId.replace(/^section-details-/, '')]; }
            }
            if (data && data.hidden) {
                $el.prop('open', false);
            } else if (data && data.hidden === false) {
                $el.prop('open', true);
            }
        });
    }

    // --- Message show/hide states ---
    if (message_show_hide) {
        // Perf optimization: when container is a single message card, extract its
        // message-id and do a direct O(1) map lookup instead of iterating ALL keys
        // and running a .find() for each (which wastes ~39 DOM queries on a 40-card load).
        var _singleCardId = null;
        if ($container.hasClass('message-card')) {
            var _singleHeader = $container.find('.card-header[message-id]').first();
            if (_singleHeader.length) {
                _singleCardId = _singleHeader.attr('message-id');
            }
        }

        if (_singleCardId && message_show_hide[_singleCardId] !== undefined) {
            // Fast path: single card — process only the matching entry
            var _ids = [_singleCardId];
        } else if (_singleCardId) {
            // Single card but no matching state — nothing to do
            var _ids = [];
        } else {
            // Full-view path: process all entries (unchanged behavior)
            var _ids = Object.keys(message_show_hide);
        }
        _ids.forEach(function(messageId) {
            var showHide = message_show_hide[messageId];
            var $header = $container.find('.card-header[message-id="' + messageId + '"]');
            if (!$header.length) return;
            var $card = $header.closest('.card.message-card');
            // Tabbed responses: collapse the tab CONTENT via the dedicated toggle path
            // (the #message-render-space / .more-text source is force-hidden under tabs).
            var $tabsContainer = $card.find('.chat-card-body[data-has-tabs]').length
                ? $card.find('.model-tabs-container').first() : $();
            if ($tabsContainer.length) {
                if (typeof ensureTabsAnswerToggle === 'function') {
                    try { ensureTabsAnswerToggle($tabsContainer); } catch (e) { /* ignore */ }
                }
                if (typeof applyTabsCollapsedState === 'function') {
                    applyTabsCollapsedState($tabsContainer, showHide === 'hide');
                }
                return;
            }
            var $moreText = $card.find('.more-text');
            var $lessText = $card.find('.less-text');
            var $showMoreLinks = $card.find('.show-more');
            if (!$moreText.length) return;

            if (showHide === 'show') {
                $moreText.show();
                $lessText.hide();
                $showMoreLinks.each(function() { $(this).text('[hide]'); });
                // Sync TOC: show if the container has content; collapse body in compact mode
                try {
                    var $toc = $card.find('.message-toc-container').first();
                    var _uiCompact = document.body.classList.contains('compact-nav');
                    if ($toc.length && $toc.children().length > 0) {
                        if (_uiCompact) {
                            _tocCollapseForCompact($toc);
                        } else {
                            $toc.show();
                        }
                    }
                } catch (e) { /* ignore */ }
            } else if (showHide === 'hide') {
                $moreText.hide();
                $lessText.show();
                $showMoreLinks.each(function() { $(this).text('[show]'); });
                // Sync TOC: hide with message
                try {
                    $card.find('.message-toc-container').first().hide();
                } catch (e) { /* ignore */ }
            }
        });
    }
}

/**
 * Unified fetch for conversation UI state — section collapse states AND
 * message show/hide.  Cache-first: when the state was already delivered via
 * /list_messages_by_conversation?include_ui_state=true it applies from the
 * client cache with NO network call (avoiding a redundant second conversation
 * load on the server). Falls back to /get_conversation_ui_state otherwise.
 *
 * @param {string} conversation_id
 * @param {HTMLElement} elem_to_render_in  — container to apply states to (usually #chatView)
 */
function fetchConversationUIState(conversation_id, elem_to_render_in) {
    if (!conversation_id || MOCK_SECTION_STATE_API) return;

    // Cache-first — no second backend conversation load.
    if (window.ConversationUIState && window.ConversationUIState.has(conversation_id)) {
        // Skip the DOM walk if the synchronous per-card apply in
        // renderInnerContentAsMarkdown already painted the final state this render pass.
        if (window.ConversationUIState.isApplied(conversation_id)) {
            return;
        }
        var entry = window.ConversationUIState.get(conversation_id);
        applyConversationUIState(entry.section_details, entry.message_show_hide, elem_to_render_in);
        return;
    }

    $.ajax({
        url: '/get_conversation_ui_state/' + encodeURIComponent(conversation_id),
        method: 'GET',
        success: function(response) {
            if (!response) return;
            if (window.ConversationUIState) {
                window.ConversationUIState.set(conversation_id, response.section_details || {}, response.message_show_hide || {});
            }
            applyConversationUIState(response.section_details, response.message_show_hide, elem_to_render_in);
        },
        error: function(xhr, status, error) {
            console.error('Failed to fetch conversation UI state:', error);
        }
    });
}


// Helper function to persist section state when toggled
function persistSectionState(conversation_id, sectionHash, isHidden) {
    // Skip API call if mocking is enabled
    if (MOCK_SECTION_STATE_API) return;
    
    const sectionDetails = {};
    sectionDetails[sectionHash] = { hidden: isHidden };
    // Keep the client UI-state cache authoritative so a later cache-first
    // fetchConversationUIState / re-render doesn't revert this toggle.
    if (window.ConversationUIState) {
        window.ConversationUIState.updateSection(conversation_id, sectionHash, isHidden);
    }
    
    $.ajax({
        url: '/update_section_hidden_details',
        method: 'POST',
        contentType: 'application/json',
        data: JSON.stringify({
            conversation_id: conversation_id,
            section_details: sectionDetails
        }),
        success: function(response) {
            // [DEBUG] console.log('Section state persisted:', response);
        },
        error: function(xhr, status, error) {
            console.error('Failed to persist section state:', error);
        }
    });
}

/**
 * Lightweight djb2-style hash used to build stable, deterministic section IDs
 * from section content. Defined at module level so it is available everywhere
 * in this file without being re-declared inside render functions or loop bodies.
 * Pure function — no side effects, no outer state.
 */
function simpleHash(str) {
    let hash = 0;
    if (str.length === 0) return hash.toString();
    for (let i = 0; i < str.length; i++) {
        const char = str.charCodeAt(i);
        hash = ((hash << 5) - hash) + char;
        hash = hash & hash;
    }
    return Math.abs(hash).toString(16).substring(0, 8);
}

/**
 * Fuzzy-match `needle` against `haystack` with scored sequential character matching.
 *
 * Returns { score: number, indexes: number[] } on a match, or null if the needle
 * cannot be matched.  Higher score = better match.  Scoring rules:
 *   - Exact substring match:  score = nLen × bonus (2.0 start, 1.8 word-boundary, 1.5 mid) + 1/(pos+1)
 *   - Consecutive chars:  +1.0 per char
 *   - Word-boundary chars:  +0.8 per char
 *   - Mid-word chars:  +0.3 − 0.005 × gap
 *   - Length penalty:  −0.01 × (hLen − nLen)
 *
 * Pure function — no side effects, no outer state.
 * Originally lived in file-browser-manager.js; ported to common.js so it can be
 * shared with the slash-command autocomplete in common-chat.js.
 *
 * @param {string} needle
 * @param {string} haystack
 * @returns {{score: number, indexes: number[]}|null}
 */
function fuzzyMatch(needle, haystack) {
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
                if (hi === lastMatchIdx + 1) {
                    score += 1.0;  // consecutive
                } else if (hi === 0 || '/\\-_. '.indexOf(hLower[hi - 1]) !== -1) {
                    score += 0.8;  // word boundary
                } else {
                    score += 0.3;  // mid-word
                    score -= (hi - lastMatchIdx - 1) * 0.005;  // gap penalty
                }
                lastMatchIdx = hi;
                hIdx = hi + 1;
                found = true;
                break;
            }
        }
        if (!found) return null;
    }

    score -= (hLen - nLen) * 0.01;  // length penalty
    return { score: score, indexes: indexes };
}

/**
 * Escape a string for safe insertion into HTML text content or double/single-quoted attributes.
 * Escapes: & < > " ' (five entities — strict superset of all local copies in this codebase).
 * Handles null/undefined/non-string input safely.
 *
 * This is the single canonical HTML-escape helper for the entire UI.  All per-file copies
 * (_escHtml, _escapeHtml, escapeDocHtml, _doubtEscapeHtml, etc.) are removed in favour of
 * this function, which is loaded first via common.js and therefore available to every script.
 *
 * @param {string|null|undefined} str
 * @returns {string}
 */
function escapeHtml(str) {
    if (str == null) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

/**
 * Returns true if the character at position `idx` in `str` is at the start of
 * a line — i.e. every character between the preceding newline (or the string
 * start) and `idx` is only whitespace (space or tab).
 *
 * Used by extractCodeBlocks to determine whether a fence token (``` or ~~~) is
 * a genuine fenced-code-block opener rather than an inline occurrence mid-line.
 * Defined at module level — pure function, closes over nothing.
 */
function isFenceLine(str, idx) {
    var pos = idx - 1;
    while (pos >= 0 && str[pos] !== '\n') {
        if (str[pos] !== ' ' && str[pos] !== '\t') return false;
        pos--;
    }
    return true;
}

function renderInnerContentAsMarkdown(jqelem, callback = null, continuous = false, html = null, immediate_callback = null, defer_mathjax = false, skip_deferred_formatting = false) {
    var _rimT = _perfStart('renderInner');
    /**
     * Render markdown/HTML content into a DOM element with MathJax typesetting,
     * model response tabs, ToC generation, and showMore() support.
     *
     * @param {jQuery}   jqelem             - Target element to render into
     * @param {Function} callback           - Callback queued AFTER MathJax typesetting (async)
     * @param {boolean}  continuous          - true = streaming (incremental), false = final render
     * @param {string}   html               - Raw HTML/markdown to render (null = use jqelem content)
     * @param {Function} immediate_callback  - Callback that runs SYNCHRONOUSLY after HTML render
     *                                         (before MathJax). Use for showMore(), addScrollToTopButton()
     *                                         so they don't wait for MathJax.
     * @param {boolean}  defer_mathjax       - When true, MathJax typesetting is deferred via
     *                                         setTimeout(0) so higher-priority cards (e.g. the last
     *                                         message) get processed first. Default: false.
     * @param {boolean}  skip_deferred_formatting - When true, skip applyModelResponseTabs,
     *                                         updateMessageTocForElement, and applyConversationUIState.
     *                                         Used for cards that will be collapsed by showMore() —
     *                                         these are invisible and get re-applied on first expand
     *                                         via the delegated toggle handler (R1 optimization).
     *
     * Purpose:
     * Central rendering function for chat messages. Converts markdown to HTML,
     * handles streaming vs final render, processes answer_tldr tags, builds
     * model response tabs, generates ToC, and queues MathJax typesetting.
     */
    // NOTE: Scroll preservation is handled ONCE at the outermost level in the streaming
    // finalization handler (common-chat.js). We do NOT capture/restore here because
    // multiple nested restores fight each other and cause progressive scroll drift.
    
    conversation_id = (typeof ConversationManager !== 'undefined' && ConversationManager && ConversationManager.getActiveConversation()!= '') ? ConversationManager.getActiveConversation() : '';
    parent = jqelem.parent()
    elem_id = jqelem.attr('id');
    elem_to_render_in = jqelem
    brother_elem_id = elem_id + "-md-render"
    elem_to_render_in.attr('data-model-tabs-root', 'true');
    if (continuous) {
        brother_elem = parent.find('#' + brother_elem_id);
        if (!brother_elem.length) {
            var brother_elem = $('<div/>', { id: brother_elem_id })
            parent.append(brother_elem);
        }
        jqelem.hide();
        brother_elem.show();
        elem_to_render_in = brother_elem

    } else {
        jqelem.show();
        brother_elem = parent.find('#' + brother_elem_id);
        if (brother_elem.length) {
            brother_elem.hide();
        }
    }

    if (html == null) {
        try {
            html = jqelem.html()
        } catch (error) {
            try { html = jqelem[0].innerHTML } catch (error) { html = jqelem.innerHTML }
        }
    }
    // remove <answer> and </answer> tags
    // check html has </answer> tag
    has_end_answer_tag = html.includes('</answer>')
    html = html.replace(/<answer>/g, '').replace(/<\/answer>/g, '');
    // Convert <answer_diff> tags to divs with data attributes (persisted model comparison data)
    // Fast indexOf gate: skip all regex work when tag is absent (~95% of messages)
    if (html.indexOf('answer_diff') !== -1) {
        var _diffOpenCount = (html.match(/<\s*answer_diff\s/gi) || []).length;
        var _diffCloseCount = (html.match(/<\s*\/\s*answer_diff\s*>/gi) || []).length;
        if (_diffOpenCount > 0 && _diffOpenCount === _diffCloseCount) {
            // All blocks complete — safe to convert
            html = html.replace(/<\s*answer_diff\s+model="([^"]*?)"\s+vs="([^"]*?)"\s*>/gi, '<div data-answer-diff="true" data-diff-model="$1" data-diff-vs="$2">')
                .replace(/<\s*\/\s*answer_diff\s*>/gi, '</div>');
        } else if (_diffOpenCount > _diffCloseCount) {
            // Some blocks still streaming — convert only complete pairs, hide incomplete
            // Convert matched pairs first
            for (var _di = 0; _di < _diffCloseCount; _di++) {
                html = html.replace(/<\s*answer_diff\s+model="([^"]*?)"\s+vs="([^"]*?)"\s*>/, '<div data-answer-diff="true" data-diff-model="$1" data-diff-vs="$2">');
                html = html.replace(/<\s*\/\s*answer_diff\s*>/, '</div>');
            }
            // Hide remaining unclosed opening tags
            html = html.replace(/<\s*answer_diff[^>]*>/gi, '<!--answer_diff_pending-->');
        }
    }
    // Streaming-safety for <answer_tldr>:
    // During streaming, we may receive the opening tag before the closing tag arrives.
    // Converting an unclosed <answer_tldr> into a <div> produces malformed HTML, and browsers
    // can auto-close at the end of the container, effectively wrapping the rest of the message
    // (including the main answer) inside the TLDR wrapper. That can trigger premature tab-building
    // and hide the main answer while TLDR is still being generated.
    // Fast indexOf gate: skip all regex work when tag is absent (~95% of messages)
    if (html.indexOf('answer_tldr') !== -1) {
        var hasOpenAnswerTldr = /<\s*answer_tldr\s*>/i.test(html);
        var hasCloseAnswerTldr = /<\s*\/\s*answer_tldr\s*>/i.test(html);
        // console.warn('[renderInnerContentAsMarkdown] answer_tldr: open=' + hasOpenAnswerTldr + ', close=' + hasCloseAnswerTldr);
        if (continuous && hasOpenAnswerTldr && !hasCloseAnswerTldr) {
            // Do NOT create a wrapper div until the closing tag arrives.
            // Remove the opening tag so inner <details> can still render, but we don't create a stable TLDR wrapper yet.
            html = html.replace(/<\s*answer_tldr\s*>/gi, '<!--answer_tldr_pending-->');
        } else {
            html = html.replace(/<\s*answer_tldr\s*>/gi, '<div data-answer-tldr="true">')
                .replace(/<\s*\/\s*answer_tldr\s*>/gi, '</div>');
        }
    }

    // Convert <answer_visual> tags: use comment placeholders so they survive marked processing
    // (marked treats <div> as HTML blocks and won't render markdown inside them).
    // The actual div conversion happens AFTER marked renders the content.
    // Fast indexOf gate: skip all regex work when tag is absent (~95% of messages)
    if (html.indexOf('answer_visual') !== -1) {
        var hasOpenAnswerVisual = /<\s*answer_visual\s*>/i.test(html);
        var hasCloseAnswerVisual = /<\s*\/\s*answer_visual\s*>/i.test(html);
        // [DEBUG] console.warn('[renderInnerContentAsMarkdown] FOUND answer_visual in input | continuous:', continuous, '| len:', html.length, '| hasOpen:', hasOpenAnswerVisual, '| hasClose:', hasCloseAnswerVisual);
        if (hasOpenAnswerVisual && hasCloseAnswerVisual) {
            // Both tags present — safe to convert
            html = html.replace(/<\s*answer_visual\s*>/gi, '<!--ANSWER_VISUAL_OPEN-->')
                .replace(/<\s*\/\s*answer_visual\s*>/gi, '<!--ANSWER_VISUAL_CLOSE-->');
        } else if (hasOpenAnswerVisual && !hasCloseAnswerVisual) {
            // Opening tag without closing — strip it to prevent malformed HTML during streaming
            html = html.replace(/<\s*answer_visual\s*>/gi, '');
        } else if (!hasOpenAnswerVisual && hasCloseAnswerVisual) {
            // Closing tag without opening — strip it
            html = html.replace(/<\s*\/\s*answer_visual\s*>/gi, '');
        }
    }

    // Check if we should wrap sections (you might want to make this configurable)
    var wrapSectionsInDetails = true; // You can make this configurable via options
    // var horizontalRuleRegex = /\n---+\s*\n/g;
    var horizontalRuleRegex = /^---+\s*$/gm;
    var hasHorizontalRules = horizontalRuleRegex.test(html);
    horizontalRuleRegex.lastIndex = 0;

    if (wrapSectionsInDetails && hasHorizontalRules) {
        // Generate a unique session ID for this extraction run to avoid placeholder collisions
        // between nested extractions or with user content that might contain placeholder-like strings
        var extractionSessionId = Date.now().toString(36) + Math.random().toString(36).substr(2, 9);
        
        // R3: closure flag — set to true when processContentWithDetails fully renders all sections,
        // allowing us to skip the redundant global marked.marked() call at the bottom.
        var _sectionsFullyRendered = false;
        
        // Function to extract and protect code blocks before processing
        // Uses unique placeholder IDs to prevent collisions between outer/inner extractions
        function extractCodeBlocks(content, sessionSuffix) {
            var codeBlocks = [];
            var codePlaceholders = [];
            var workingContent = content;
            // Use provided suffix or generate a new one for nested calls
            var uniqueSuffix = sessionSuffix || (Date.now().toString(36) + Math.random().toString(36).substr(2, 5));
            
            function replaceWithPlaceholder(match) {
                var placeholder = `\x00CB${uniqueSuffix}_${codeBlocks.length}\x00`;
                codeBlocks.push(match);
                codePlaceholders.push(placeholder);
                return placeholder;
            }
            
            // Replace all complete fenced code blocks first (``` and ~~~)
            var tripleBacktickRegex = /```[\s\S]*?```/g;
            var tripleTildeRegex = /~~~[\s\S]*?~~~/g;
            workingContent = workingContent.replace(tripleBacktickRegex, replaceWithPlaceholder);
            workingContent = workingContent.replace(tripleTildeRegex, replaceWithPlaceholder);
            
            function protectIncompleteFence(fenceToken) {
                var startIdx = workingContent.lastIndexOf(fenceToken);
                while (startIdx !== -1) {
                    if (isFenceLine(workingContent, startIdx)) {
                        var closingIdx = workingContent.indexOf(fenceToken, startIdx + fenceToken.length);
                        if (closingIdx === -1) {
                            var placeholder = `\x00CB${uniqueSuffix}_${codeBlocks.length}\x00`;
                            var segment = workingContent.substring(startIdx);
                            codeBlocks.push(segment);
                            codePlaceholders.push(placeholder);
                            workingContent = workingContent.substring(0, startIdx) + placeholder;
                            break;
                        }
                    }
                    startIdx = workingContent.lastIndexOf(fenceToken, startIdx - 1);
                }
            }
            
            // Protect streaming scenarios where closing fence hasn't arrived yet
            protectIncompleteFence('```');
            protectIncompleteFence('~~~');
            
            // Handle inline code with completed backticks
            workingContent = workingContent.replace(/`[^`\n]+`/g, function(match) {
                var placeholder = `\x00IC${uniqueSuffix}_${codeBlocks.length}\x00`;
                codeBlocks.push(match);
                codePlaceholders.push(placeholder);
                return placeholder;
            });
            
            // Protect trailing unmatched inline code (e.g., streaming chunk)
            var inlineBacktickCount = (workingContent.match(/`/g) || []).length;
            if (inlineBacktickCount % 2 === 1) {
                var unmatchedIndex = workingContent.lastIndexOf('`');
                if (unmatchedIndex !== -1) {
                    var inlinePlaceholder = `\x00IC${uniqueSuffix}_${codeBlocks.length}\x00`;
                    var inlineSegment = workingContent.substring(unmatchedIndex);
                    codeBlocks.push(inlineSegment);
                    codePlaceholders.push(inlinePlaceholder);
                    workingContent = workingContent.substring(0, unmatchedIndex) + inlinePlaceholder;
                }
            }
            
            return {
                content: workingContent,
                codeBlocks: codeBlocks,
                placeholders: codePlaceholders
            };
        }
        
        // Maximum allowed string size to prevent runaway growth (50MB)
        var MAX_RESTORED_SIZE = 50 * 1024 * 1024;
        
        // Function to restore code blocks in content
        // Uses split/join for safer single-replacement and includes size checks
        function restoreCodeBlocks(content, codeBlocks, placeholders) {
            if (!content || !placeholders || placeholders.length === 0) {
                return content;
            }
            
            var restoredContent = content;
            var originalLength = content.length;
            
            // Pre-compute the sum of all code block lengths once — this is a constant
            // across all loop iterations. Moving it out of the loop eliminates O(N²) work.
            var totalCodeBlockSize = codeBlocks.reduce(function(sum, cb) {
                return sum + (cb ? cb.length : 0);
            }, 0);
            var expectedMaxSize = originalLength + totalCodeBlockSize;
            
            for (var i = 0; i < placeholders.length; i++) {
                var placeholder = placeholders[i];
                var codeBlock = codeBlocks[i];
                
                // Skip if placeholder or codeBlock is undefined/null
                if (!placeholder || codeBlock === undefined || codeBlock === null) {
                    continue;
                }
                
                // Check if placeholder exists in content before replacing
                var placeholderIndex = restoredContent.indexOf(placeholder);
                if (placeholderIndex === -1) {
                    continue; // Placeholder not found, skip
                }
                
                // Use split/join for exact single replacement (safer than replace)
                // This ensures we only replace the exact placeholder once
                var parts = restoredContent.split(placeholder);
                if (parts.length === 2) {
                    // Normal case: exactly one occurrence
                    restoredContent = parts[0] + codeBlock + parts[1];
                } else if (parts.length > 2) {
                    // Multiple occurrences (shouldn't happen, but handle defensively)
                    // Only replace the first occurrence
                    restoredContent = parts[0] + codeBlock + parts.slice(1).join(placeholder);
                }
                
                // Defensive check: prevent runaway string growth
                if (restoredContent.length > MAX_RESTORED_SIZE) {
                    console.warn('restoreCodeBlocks: String size exceeded limit, truncating restoration at index', i);
                    break;
                }
                
                // Additional check: if string grew more than 2x (original + all code blocks), something is wrong
                if (restoredContent.length > expectedMaxSize * 2) {
                    console.warn('restoreCodeBlocks: Unexpected string growth detected, stopping restoration');
                    break;
                }
            }
            
            return restoredContent;
        }

        // Function to process sections while preserving existing details tags
        function processContentWithDetails(content) {
            // R-H3: Pre-normalize the full content ONCE before splitting into sections.
            // Both functions are line-by-line transforms that already skip code blocks
            // (they track inCodeBlock state internally).  Running them once here
            // eliminates N redundant split('\n') + join('\n') cycles (one per section)
            // inside the loop below.
            var _normT = _perfStart('pcd_normalize');
            content = normalizeMathBlocks(normalizeOverIndentedLists(content));
            _perfEnd('pcd_normalize', _normT);

            // Extract code blocks first to protect them from splitting
            // Pass the extractionSessionId to ensure consistent placeholders at the outer level
            var _extractT = _perfStart('pcd_extractCodeBlocks');
            var codeExtraction = extractCodeBlocks(content, extractionSessionId);
            var contentWithCodePlaceholders = codeExtraction.content;
            var codeBlocks = codeExtraction.codeBlocks;
            var codePlaceholders = codeExtraction.placeholders;
            _perfEnd('pcd_extractCodeBlocks', _extractT);
            
            // Now preserve existing <details> tags
            // Use a unique suffix for details placeholders to avoid collision with user content
            var _detailsExtractT = _perfStart('pcd_detailsExtract');
            var detailsPlaceholderSuffix = Date.now().toString(36) + Math.random().toString(36).substr(2, 5);
            var detailsRegex = /<details[^>]*>[\s\S]*?<\/details>/gi;
            var detailsBlocks = [];
            var placeholders = [];
            
            // Extract and store existing details blocks
            var match;
            var tempContent = contentWithCodePlaceholders;
            while ((match = detailsRegex.exec(contentWithCodePlaceholders)) !== null) {
                // Use null character delimiters to avoid collision with user content
                var placeholder = `\x00DP${detailsPlaceholderSuffix}_${placeholders.length}\x00`;
                detailsBlocks.push(match[0]);
                placeholders.push(placeholder);
            }
            
            // Replace details blocks with placeholders temporarily
            // Use indexOf + substring for safer single-replacement (avoids regex special chars issues)
            var workingContent = contentWithCodePlaceholders;
            for (var i = 0; i < detailsBlocks.length; i++) {
                var detailsIndex = workingContent.indexOf(detailsBlocks[i]);
                if (detailsIndex !== -1) {
                    workingContent = workingContent.substring(0, detailsIndex) + 
                                     placeholders[i] + 
                                     workingContent.substring(detailsIndex + detailsBlocks[i].length);
                }
            }
            _perfEnd('pcd_detailsExtract', _detailsExtractT);
            
            // Now split the content by horizontal rules (which are now safe from code blocks)
            var _sectionLoopT = _perfStart('pcd_sectionLoop');
            var sections = workingContent.split(horizontalRuleRegex);
            horizontalRuleRegex.lastIndex = 0;
            
            if (sections.length > 1) {
                var wrappedHtml = '';
                var _markedCumulativeMs = 0;
                var _markedCallCount = 0;
                var _restoreCumulativeMs = 0;
                
                // Timed wrapper around marked.marked() — accumulates total time
                function _timedMarked(input) {
                    var t0 = performance.now();
                    var result = marked.marked(input, { renderer: markdownParser });
                    _markedCumulativeMs += performance.now() - t0;
                    _markedCallCount++;
                    return result;
                }
                // Timed wrapper around restoreCodeBlocks — accumulates total time
                function _timedRestore(content, blocks, placeholders) {
                    var t0 = performance.now();
                    var result = restoreCodeBlocks(content, blocks, placeholders);
                    _restoreCumulativeMs += performance.now() - t0;
                    return result;
                }
                
                sections.forEach(function(section, sectionIndex) {
                    section = section.trim();
                    
                    // Check if this section contains a details placeholder
                    var hasPlaceholder = placeholders.some(p => section.includes(p));
                    
                    if (hasPlaceholder) {
                        // Process sections that contain placeholders
                        for (var i = 0; i < placeholders.length; i++) {
                            if (section.includes(placeholders[i])) {
                                // Process the content inside the details block recursively
                                var detailsBlock = detailsBlocks[i];
                                var detailsMatch = detailsBlock.match(/<details[^>]*>([\s\S]*?)<\/details>/i);
                                
                                if (detailsMatch) {
                                    var detailsOpening = detailsBlock.match(/<details[^>]*>/)[0];
                                    var detailsContent = detailsMatch[1];
                                    
                                    // Extract code blocks from inner content before processing
                                    var innerCodeExtraction = extractCodeBlocks(detailsContent);
                                    var innerContentWithCodePlaceholders = innerCodeExtraction.content;
                                    var innerCodeBlocks = innerCodeExtraction.codeBlocks;
                                    var innerCodePlaceholders = innerCodeExtraction.placeholders;
                                    
                                    // Check if the inner content has --- horizontal rules (not in code blocks)
                                    var hasHorizontalRules = horizontalRuleRegex.test(innerContentWithCodePlaceholders);
                                    horizontalRuleRegex.lastIndex = 0;
                                    
                                    if (hasHorizontalRules) {
                                        // Process inner content: only wrap sections between --- horizontal rule markers
                                        // Reset regex for splitting since test() advances the lastIndex
                                        var innerSections = innerContentWithCodePlaceholders.split(horizontalRuleRegex);
                                        horizontalRuleRegex.lastIndex = 0;
                                        if (innerSections.length > 1) {
                                            var innerWrapped = '';
                                            
                                            // First section (before first ---) — pre-render markdown (R3 optimisation)
                                            if (innerSections[0].trim()) {
                                                var firstSection = _timedRestore(innerSections[0].trim(), innerCodeBlocks, innerCodePlaceholders);
                                                // Check if it has a summary tag (from server) — pass through as-is (HTML survives marked)
                                                var summaryMatch = firstSection.match(/<summary[^>]*>(.*?)<\/summary>/i);
                                                if (summaryMatch) {
                                                    innerWrapped += firstSection;
                                                } else {
                                                    innerWrapped += _timedMarked(firstSection);
                                                }
                                            }
                                            
                                            // Middle sections (between --- markers) get wrapped
                                            for (var j = 1; j < innerSections.length; j++) {
                                                var innerSection = innerSections[j].trim();
                                                if (innerSection) {
                                                    // Restore code blocks in this section before generating summary
                                                    var innerSectionWithCode = _timedRestore(innerSection, innerCodeBlocks, innerCodePlaceholders);
                                                    var innerSummary = generateSectionSummary(innerSectionWithCode, j - 1);
                                                    var innerHash = simpleHash(innerSectionWithCode) || 
                                                        (innerSectionWithCode.length.toString() + innerSectionWithCode.replace(/[^a-zA-Z0-9]/g, '').substring(0, 4)).substring(0, 8);
                                                    var innerId = `section-details-${conversation_id}-${innerHash}`;
                                                    
                                                    innerSummary = innerSummary.replace(/<answer>/g, '').replace(/<\/answer>/g, '').replace(/\*/g, '');
                                                    innerSectionWithCode = innerSectionWithCode.trim();
                                                    // Pre-render markdown to HTML before wrapping in <details>
                                                    // Otherwise marked.js treats content inside HTML blocks as raw text
                                                    var innerSectionRendered = _timedMarked(innerSectionWithCode);
                                                     
                                                     innerWrapped += `
<details open class="section-details nested-section" data-section-index="${j - 1}" data-section-hash="${innerHash}" id="${innerId}">
<summary class="section-summary"><strong>${innerSummary}</strong></summary>

<br/>


<div class="section-content">
<br/>\n
${innerSectionRendered}

` + `

<div class="section-footer">
<button class="close-section-btn btn btn-xs btn-secondary" onclick="closeSectionDetails('${innerId}')" data-section-id="${innerId}" style="font-size: 10px; padding: 2px 6px;">Close Section</button>
</div>
</div>
</details>
`;
                                                }
                                            }
                                            
                                            // NOTE: The loop above (j=1..length-1) already processes the last section
                                            // by wrapping it in <details>. A previous assignment here extracted the
                                            // last section into a variable but never appended it — removed as dead code.
                                            
                                            detailsBlock = detailsOpening + innerWrapped + '</details>';
                                        }
                                    }
                                    section = section.replace(placeholders[i], detailsBlock);
                                } else {
                                    section = section.replace(placeholders[i], detailsBlocks[i]);
                                }
                            }
                        }
                        // Restore code blocks in the section with restored details
                        section = _timedRestore(section, codeBlocks, codePlaceholders);
                        // R3: pre-render any raw markdown surrounding <details> blocks
                        // The <details> HTML passes through marked unchanged (sanitize: false)
                        wrappedHtml += _timedMarked(section);
                    } else {
                        // Handle sections without placeholders
                        // Only wrap if this is a middle section (not first or last)
                        if (sectionIndex === 0) {
                            // First section - don't wrap, but pre-render markdown (R3 optimisation)
                            if (section) {
                                var sectionWithCode = _timedRestore(section, codeBlocks, codePlaceholders);
                                wrappedHtml += _timedMarked(sectionWithCode) + '\n';
                            }
                        } else if (sectionIndex === sections.length - 1) {
                            // Last section - don't wrap, but pre-render markdown (R3 optimisation)
                            if (section) {
                                var sectionWithCode = _timedRestore(section, codeBlocks, codePlaceholders);
                                wrappedHtml += '\n' + _timedMarked(sectionWithCode);
                            }
                        } else {
                            // Middle section - wrap in details
                            if (section) {
                                // Restore code blocks before generating summary and wrapping
                                var sectionWithCode = _timedRestore(section, codeBlocks, codePlaceholders);
                                var summary = generateSectionSummary(sectionWithCode, sectionIndex - 1);
                                var sectionHash = simpleHash(sectionWithCode) || 
                                    (sectionWithCode.length.toString() + sectionWithCode.replace(/[^a-zA-Z0-9]/g, '').substring(0, 4)).substring(0, 8);
                                
                                sectionHash = `${conversation_id}-${sectionHash}`;
                                var sectionId = `section-details-${sectionHash}`;
                                
                                summary = summary.replace(/<answer>/g, '').replace(/<\/answer>/g, '').replace(/\*/g, '');
                                // Pre-render markdown to HTML before wrapping in <details>
                                // Otherwise marked.js treats content inside HTML blocks as raw text
                                var                                 sectionRendered = _timedMarked(sectionWithCode);
                                wrappedHtml += `
<details open class="section-details" data-section-index="${sectionIndex - 1}" data-section-hash="${sectionHash}" id="${sectionId}">
    <summary class="section-summary"><strong>${summary}</strong></summary>
    <div class="section-content">
        ${sectionRendered}
        <div class="section-footer">
            <button class="close-section-btn btn btn-xs btn-secondary" onclick="closeSectionDetails('${sectionId}')" data-section-id="${sectionId}" style="font-size: 10px; padding: 2px 6px;">Close Section</button>
        </div>
    </div>
</details>`;
                            }
                        }
                    }
                });
                
                // R3: all sections (first, middle, last) are now fully rendered HTML
                _sectionsFullyRendered = true;
                // Record cumulative marked.marked() and restoreCodeBlocks() time
                if (window._PERF && _markedCallCount > 0) {
                    window._perfTimings = window._perfTimings || {};
                    window._perfTimings['pcd_marked_cumulative'] = window._perfTimings['pcd_marked_cumulative'] || [];
                    window._perfTimings['pcd_marked_cumulative'].push(_markedCumulativeMs);
                    window._perfTimings['pcd_restore_cumulative'] = window._perfTimings['pcd_restore_cumulative'] || [];
                    window._perfTimings['pcd_restore_cumulative'].push(_restoreCumulativeMs);
                    // Store call counts for analysis (not displayed in summary table)
                    window._pcdMarkedCallCounts = window._pcdMarkedCallCounts || [];
                    window._pcdMarkedCallCounts.push(_markedCallCount);
                }
                _perfEnd('pcd_sectionLoop', _sectionLoopT);
                return wrappedHtml;
            }
            
            // No sections to split, return original content with placeholders restored
            _perfEnd('pcd_sectionLoop', _sectionLoopT);
            for (var i = 0; i < placeholders.length; i++) {
                workingContent = workingContent.replace(placeholders[i], detailsBlocks[i]);
            }
            // Restore code blocks
            workingContent = restoreCodeBlocks(workingContent, codeBlocks, codePlaceholders);
            return workingContent;
        }
        
        var _pcdT = _perfStart('processContentWithDetails');
        html = processContentWithDetails(html);
        _perfEnd('processContentWithDetails', _pcdT);
    }

    // Check if this input contains slide presentation tags at all
    var hasSlideTags = html.includes('<slide-presentation>');
    var isSlidePresentation = hasSlideTags; // Backward-compatible flag used below
    var htmlChunk;

    if (hasSlideTags) {
        var split = splitSlidePresentationParts(html);
        var combined = '';
        var foundSlide = false;
        for (var pi = 0; pi < split.parts.length; pi++) {
            var part = split.parts[pi];
            if (part.type === 'text') {
                var renderedText = marked.marked(normalizeMathBlocks(normalizeOverIndentedLists(part.content)), { renderer: markdownParser });
                combined += renderedText;
            } else if (part.type === 'slide') {
                foundSlide = true;
                var rawSlideInnerHtml = part.content.trim();
                var fullDocument = isFullHtmlDocument(rawSlideInnerHtml);
                var htmlForBlob;
                if (fullDocument) {
                    htmlForBlob = rawSlideInnerHtml;
                } else {
                    var cleaned = rawSlideInnerHtml
                        .replace(/<script[\s\S]*?<\/script>/gi, '')
                        .replace(/<div[^>]*class=["']?slide-controls[^>]*>[\s\S]*?<\/div>/gi, '');
                    var sectionsOnly = extractSectionsFromReveal(cleaned);
                    htmlForBlob = buildStandaloneSlidesPage(sectionsOnly);
                }
                var blobUrl = createSlidesBlobUrl(htmlForBlob);
                var linkId = 'slide-link-' + Date.now() + '-' + Math.random().toString(36).substr(2, 9);
                
                // Check if inline rendering is enabled
                var renderInline = false;
                try {
                    // Get the current options to check if inline rendering is enabled
                    // TODO: this seems broken
                    var options = getOptions('chat-controls', 'assistant');
                    renderInline = options.render_slides_inline || false;
                } catch (e) {
                    console.log('Could not get inline rendering option:', e);
                }
                
                if (renderInline) {
                    // Render both iframe inline and external link
                    var iframeId = 'slide-iframe-' + Date.now() + '-' + Math.random().toString(36).substr(2, 9);
                    combined += `
                        <div class="slide-presentation-container" data-has-slides="true">
                            <div class="slide-external-link mb-3">
                                <a id="${linkId}" href="${blobUrl}" target="_blank" rel="noopener noreferrer">
                                    <i class="bi bi-box-arrow-up-right"></i> Click here to view slides in new window
                                </a>
                            </div>
                            <div class="slide-iframe-wrapper" style="width: 100%; border: 1px solid #dee2e6; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 10px rgba(0, 0, 0, 0.1);">
                                <iframe id="${iframeId}" 
                                        src="${blobUrl}" 
                                        style="width: 100%; height: 600px; border: none; background: #fff;"
                                        allowfullscreen="true"
                                        sandbox="allow-scripts allow-same-origin">
                                </iframe>
                            </div>
                        </div>
                    `;
                } else {
                    // Only show external link
                    combined += `
                        <div class="slide-external-link" data-has-slides="true">
                            <a id="${linkId}" href="${blobUrl}" target="_blank" rel="noopener noreferrer">Click here to see slides</a>
                            <small class="text-muted" style="margin-left: 8px;">(opens in a new window)</small>
                        </div>
                    `;
                }
            }
        }
        if (split.incomplete) {
            // For streaming with an open but not yet closed slide block, render only the text parts before
            // the opening tag. When the closing tag arrives, a subsequent call will render the full content.
        }
        if (foundSlide) {
            try { elem_to_render_in.attr('data-has-slides', 'true'); } catch (e) {}
        }
        htmlChunk = combined;
    } else {
        // Normal markdown processing
        // Normalize over-indented list items BEFORE marked parses them.
        // Some LLMs indent bullets with 4+ spaces (e.g., "    *   text"),
        // which CommonMark treats as an indented code block instead of a list.
        // R3: skip global parse when processContentWithDetails already rendered all sections
        if (_sectionsFullyRendered) {
            htmlChunk = html; // already fully rendered HTML — no redundant parse
        } else {
            var _markedT = _perfStart('marked.marked');
            htmlChunk = marked.marked(normalizeMathBlocks(normalizeOverIndentedLists(html)), { renderer: markdownParser });
            _perfEnd('marked.marked', _markedT);
        }
    }

    // Post-marked: convert answer_visual comment placeholders to div wrappers
    // (done after marked so markdown inside the visual block is rendered properly)
    // Fast indexOf gate: skip when no placeholders present
    if (htmlChunk.indexOf('ANSWER_VISUAL') !== -1) {
        // [DEBUG] console.warn('[renderInnerContentAsMarkdown] ANSWER_VISUAL comment found in htmlChunk, converting to div');
        htmlChunk = htmlChunk.replace(/<!--ANSWER_VISUAL_OPEN-->/g, '<div data-answer-visual="true">')
            .replace(/<!--ANSWER_VISUAL_CLOSE-->/g, '</div>');
        if (htmlChunk.indexOf('data-answer-visual') !== -1) {
            // [DEBUG] console.warn('[renderInnerContentAsMarkdown] SUCCESS: data-answer-visual div is in final htmlChunk');
        }
    }
    
    // Helper for scheduling non-critical work during idle time
    // Falls back to setTimeout if requestIdleCallback is not available
    var scheduleIdleWork = window.requestIdleCallback 
        ? function(fn, options) { return window.requestIdleCallback(fn, options || { timeout: 500 }); }
        : function(fn) { return setTimeout(fn, 16); }; // ~1 frame delay as fallback
    
    // Batch DOM write operation - single innerHTML assignment is faster than empty() + append()
    var targetElement = elem_to_render_in[0] || elem_to_render_in;
    // Height lock in applyModelResponseTabs + streaming done handler prevents scroll shift
    
    // ── Reflow prevention: lock element height during continuous rendering ──
    // During streaming (continuous=true), replacing innerHTML destroys existing
    // MathJax-rendered content.  Until MathJax re-typesets the new HTML, the
    // element can shrink dramatically (raw text is shorter than formatted math),
    // causing a visible "jump".  By setting min-height to the current rendered
    // height before the replacement, we keep the element from collapsing.
    // The min-height is cleared after MathJax finishes in _queueMathJax().
    var _lockedMinHeight = false;
    if (continuous) {
        try {
            var _curHeight = targetElement.offsetHeight || 0;
            if (_curHeight > 50) { // only lock if there's meaningful rendered content
                targetElement.style.minHeight = _curHeight + 'px';
                _lockedMinHeight = true;
            }
        } catch (e) { /* ignore */ }
    }
    
    try {
        var _domWriteT = _perfStart('innerHTML');
        if (targetElement.innerHTML !== undefined) {
            targetElement.innerHTML = htmlChunk;
        } else {
            $(targetElement).html(htmlChunk);
        }
        _perfEnd('innerHTML', _domWriteT);
    } catch (error) {
        console.warn('DOM write failed, using fallback:', error);
        try { $(elem_to_render_in).html(htmlChunk); } catch (e) { /* ignore */ }
    }

    // Verify visual div survived DOM insertion
    if (htmlChunk.indexOf('data-answer-visual') !== -1) {
        var _domHasIt = targetElement.innerHTML.indexOf('data-answer-visual') !== -1;
        // [DEBUG] console.warn('[renderInnerContentAsMarkdown] POST-innerHTML | div in DOM:', _domHasIt, '| targetElement id:', targetElement.id, '| parentId:', (targetElement.parentElement||{}).id);
    }

    // Gate applyModelResponseTabs with a fast string check before touching the DOM.
    // For the vast majority of plain messages none of these markers will be present,
    // so we skip ~6 DOM traversals, a data-attribute write, and a console.warn that
    // the function emits unconditionally on non-streaming calls.
    //
    // IMPORTANT: The old gate included `htmlChunk.indexOf('<details') !== -1` which
    // was far too broad — processContentWithDetails wraps every `---`-split section
    // in `<details class="section-details">`, so ALL 69 section-bearing cards entered
    // applyModelResponseTabs only to early-exit after 5-7 jQuery .find() traversals
    // (~5ms each = ~250ms wasted).  The refined gate checks for markers that only
    // appear when tabs are actually needed:
    //   - data-answer-tldr / data-answer-visual  — server-injected wrappers
    //   - 'Response from'  — multi-model <summary> text (always present in rendered HTML)
    //   - 'TLDR Summary'   — fallback TLDR <details> from older stored messages
    //   - model-tabs-container — pre-existing tab UI from prior render
    //   - data-has-tabs on ancestor .chat-card-body — O(1) attribute set by prior render
    //
    // skip_deferred_formatting: When the card will be collapsed by showMore() (show_hide='hide'),
    // tabs and ToC are invisible.  The delegated expand handler (R1) re-applies both on
    // first [show] click, so we skip them here to save 50-200ms per collapsed card.
    if (!skip_deferred_formatting) {
        var _needsModelTabs = htmlChunk.indexOf('data-answer-tldr') !== -1
                           || htmlChunk.indexOf('data-answer-visual') !== -1
                           || htmlChunk.indexOf('Response from') !== -1
                           || htmlChunk.indexOf('TLDR Summary') !== -1
                           || htmlChunk.indexOf('model-tabs-container') !== -1
                           || (elem_to_render_in && $(elem_to_render_in).closest('.chat-card-body[data-has-tabs]').length > 0);
        if (_needsModelTabs) {
            try {
                // Clear the data-no-tabs cache before entering — the gate above
                // determined that tab-worthy markers ARE present in the fresh
                // htmlChunk, so any prior "no tabs" decision is stale.  Without
                // this, a streaming update that adds TLDR/multi-model content would
                // be blocked by the cache from a prior call that found nothing.
                try {
                    var _cacheRoot = elem_to_render_in ? $(elem_to_render_in).closest('.chat-card-body')[0] : null;
                    if (_cacheRoot) _cacheRoot.removeAttribute('data-no-tabs');
                } catch (e2) { /* ignore */ }
                var _tabsT = _perfStart('applyModelResponseTabs');
                applyModelResponseTabs(elem_to_render_in);
                _perfEnd('applyModelResponseTabs', _tabsT);
            } catch (e) {
                console.warn('Model tabs render failed:', e);
            }
        }

        // Verify visual div survived applyModelResponseTabs
        if (htmlChunk.indexOf('data-answer-visual') !== -1) {
            var _domHasItAfterTabs = targetElement.innerHTML.indexOf('data-answer-visual') !== -1;
            // [DEBUG] console.warn('[renderInnerContentAsMarkdown] POST-applyTabs | div in DOM:', _domHasItAfterTabs);
        }
    }

    // Update Table of Contents (ToC) for long answers.
    // Important: The ToC container is placed in the card-body (outside the render element),
    // so showMore() doesn't collapse it. Safe to call during streaming; internally throttled.
    // Skipped when skip_deferred_formatting=true (collapsed cards) — re-generated on expand.
    if (!skip_deferred_formatting) {
        try {
            var _tocT = _perfStart('updateMessageToc');
            updateMessageTocForElement(elem_to_render_in, html, continuous);
            _perfEnd('updateMessageToc', _tocT);
        } catch (e) {
            // Never break rendering due to ToC issues
            console.warn('ToC update failed:', e);
        }
    }

    mathjax_elem = elem_to_render_in[0] || jqelem;

    // Detect whether the content actually contains math notation.
    // MathJax 2 scans the entire DOM subtree even when there is nothing to typeset,
    // so skipping the queue call for math-free content eliminates wasted work —
    // particularly important when loading history (list_messages), where many cards
    // are rendered in sequence and most may not contain any math.
    // Patterns matched: $...$ / $$...$$  \(...\)  \[...\]  \begin{...}
    var hasMath = /(\$|\\[()\[\]]|\\begin\{)/.test(html);

    // Build a post-typeset callback that handles min-height release, slide adjust,
    // and the caller's callback — shared by both the streaming and scheduler paths.
    var _postTypesetCb = function() {
        if (_lockedMinHeight) {
            try { targetElement.style.minHeight = ''; } catch (e) { /* ignore */ }
        }
        if (isSlidePresentation) {
            requestAnimationFrame(function() {
                try {
                    var slideWrapper = $(elem_to_render_in).find('.slide-presentation-wrapper');
                    if (slideWrapper && slideWrapper.length > 0) {
                        adjustCardHeightForSlides(slideWrapper);
                    }
                } catch (e) {
                    console.warn('Post-MathJax slide height adjust failed:', e);
                }
            });
        }
        if (callback) { callback(); }
    };

    if (hasMath && !window._DISABLE_MATHJAX) {
        if (continuous) {
            // STREAMING PATH: call MathJax.Hub.Queue directly — streaming already
            // controls its own pacing (render threshold + isInsideDisplayMath gate).
            MathJax.Hub.Queue(["Typeset", MathJax.Hub, mathjax_elem]);
            MathJax.Hub.Queue(_postTypesetCb);
        } else {
            // HISTORY LOAD PATH: use the yielding scheduler (R5) so the browser
            // stays responsive between each card's typeset.  The scheduler yields
            // via setTimeout(0) between elements instead of chaining them all in
            // MathJax's synchronous FIFO queue.
            //
            // priority = !defer_mathjax → last/visible card gets typeset first.
            _mathJaxScheduler.enqueue(mathjax_elem, _postTypesetCb, !defer_mathjax);
        }
    } else {
        // No math in this block — skip MathJax entirely.
        if (_lockedMinHeight) {
            try { targetElement.style.minHeight = ''; } catch (e) { /* ignore */ }
        }
        if (callback) { callback(); }
    }

    if (immediate_callback) {
        var _icbT = _perfStart('immediate_callback');
        immediate_callback();
        _perfEnd('immediate_callback', _icbT);
    }

    _perfEnd('renderInner', _rimT);

    // Paint sections in their FINAL collapsed/expanded state synchronously — before
    // the browser paints — using the cached UI state folded into the list_messages
    // response. This removes the expand-then-collapse flash that the debounced
    // fetchConversationUIState (below) otherwise caused. No-op while streaming or
    // when the cache is empty (the debounced call then handles it). Scoped to the
    // card body so it also covers section clones inside a .model-tabs-container.
    // Skipped when skip_deferred_formatting=true (collapsed cards) — section state
    // is irrelevant when the whole card content is hidden behind [show].
    if (!skip_deferred_formatting && !continuous && !MOCK_SECTION_STATE_API) {
        try {
            var _uiStateT = _perfStart('applyUIState');
            var _uiConvId = (typeof ConversationManager !== 'undefined' && ConversationManager && ConversationManager.getActiveConversation && ConversationManager.getActiveConversation() != '') ? ConversationManager.getActiveConversation() : '';
            if (_uiConvId && window.ConversationUIState && window.ConversationUIState.has(_uiConvId)) {
                var _uiEntry = window.ConversationUIState.get(_uiConvId);
                // Scope to the whole message card so BOTH section collapse and the
                // tabbed-answer collapse paint in their final state. For expanded messages
                // (show_at_start=true), applyModelResponseTabs runs synchronously inside
                // showMore(), so .model-tabs-container exists. For collapsed messages
                // (R1 optimization), tabs are deferred to first expand — applyConversationUIState
                // checks data-has-tabs which won't be set yet, so the tab logic is safely
                // skipped. Non-tabbed messages are placed in final state via show_at_start.
                var $_uiCard = $(elem_to_render_in).closest('.card.message-card');
                var _uiScope = $_uiCard.length
                    ? $_uiCard
                    : ($(elem_to_render_in).closest('.chat-card-body').length ? $(elem_to_render_in).closest('.chat-card-body') : elem_to_render_in);
                applyConversationUIState(_uiEntry.section_details, _uiEntry.message_show_hide, _uiScope);
                window.ConversationUIState.markApplied(_uiConvId);
            }
            _perfEnd('applyUIState', _uiStateT);
        } catch (e) { /* ignore */ }
    }

    
    // Defer non-critical DOM operations to avoid blocking the main thread
    // Use requestAnimationFrame for operations that need to happen soon but shouldn't block
    requestAnimationFrame(function() {
        // Add toggle event listeners to section details elements
        // Only do this for non-streaming content (when we have complete content)
        // Re-resolve conversation_id in case it wasn't available at render start
        var resolvedConvId = conversation_id || ((typeof ConversationManager !== 'undefined' && ConversationManager && ConversationManager.getActiveConversation() != '') ? ConversationManager.getActiveConversation() : '');
        if (resolvedConvId && !continuous && !MOCK_SECTION_STATE_API) {
            // Debounce fetchConversationUIState — multiple messages render at once,
            // so batch into a single API call after all renders complete
            clearTimeout(window._sectionStateFetchTimer);
            window._sectionStateFetchTimer = setTimeout(function() {
                var $chatView = $('#chatView');
                if ($chatView.length) {
                    fetchConversationUIState(resolvedConvId, $chatView[0]);
                }
            }, 300);
        }
        
        // Slides are now opened in a new window via link; no in-card Reveal init
        
        // Cache these checks to avoid repeated DOM queries
        var mermaid_rendering_needed = !hasUnclosedMermaidTag(html) && has_end_answer_tag;
        var drawio_rendering_needed = $(elem_to_render_in).find('.drawio-diagram').length > 0;
        
        // Schedule mermaid rendering during idle time to avoid blocking UI
        if (mermaid_rendering_needed) {
            scheduleIdleWork(function() {
                var mermaidBlocks = elem_to_render_in.parent().find('pre.mermaid');
                
                if (mermaidBlocks.length > 0) {
                    // Batch all text content cleaning before any DOM writes
                    var blocksToClean = [];
                    mermaidBlocks.each(function(index, block) {
                        if (!block.querySelector('svg')) {
                            blocksToClean.push(block);
                        }
                    });
                    // Clean mermaid code helper is global: cleanMermaidCode()
                    
                    // Batch DOM writes
                    blocksToClean.forEach(function(block) {
                        var code = block.textContent || block.innerText;
                        block.textContent = cleanMermaidCode(code);
                    });
                    
                    // Run mermaid rendering
                    mermaid.run({
                        nodes: mermaidBlocks,
                        useMaxWidth: false,
                        suppressErrors: false
                    }).then(function() {
                        // Defer SVG height cleanup to next frame to avoid reflow
                        requestAnimationFrame(function() {
                            var svgs = $(elem_to_render_in).find('pre.mermaid svg');
                            svgs.each(function(index, svg) {
                                $(svg).attr('height', null);
                            });
                        });
                    }).catch(function(err) {
                        console.error('Mermaid Error:', err);
                    });
                }
            });
        }
        
        // Schedule drawio rendering during idle time
        if (drawio_rendering_needed) {
            var _drawioWork = function() {
                scheduleIdleWork(function() {
                    // Item 7: load drawio-renderer on demand
                    var doRender = function () {
                        var permittedTagNames = ["DIV", "SPAN", "SECTION", "BODY"];
                        waitForDrawIo(function(timeout) {
                            var diagrams = document.querySelectorAll(".drawio-diagram");
                            diagrams.forEach(function(diagram) {
                                if (permittedTagNames.indexOf(diagram.tagName) === -1) {
                                    return;
                                }
                                if (timeout) {
                                    showError(diagram, "Unable to load draw.io renderer");
                                    return;
                                }
                                processDiagram(diagram);
                            });
                        });
                    };
                    if (typeof waitForDrawIo === 'function') {
                        doRender();
                    } else if (typeof LazyLibs !== 'undefined') {
                        LazyLibs.loadDrawio().then(doRender).catch(function (err) {
                            console.error('Failed to load drawio-renderer:', err);
                        });
                    }
                });
            };
            // If MathJax is active, wait for its queue to flush before drawio.
            // Otherwise, just schedule immediately.
            if (!window._DISABLE_MATHJAX && typeof MathJax !== 'undefined' && MathJax.Hub) {
                MathJax.Hub.Queue(_drawioWork);
            } else {
                _drawioWork();
            }
        }
    });

    return mathjax_elem;
}


function extractLastMermaid(html) {
    /**
     * Extract the last mermaid diagram from the HTML string.
     * 
     * @param {string} html - HTML string that may contain ```mermaid code blocks or <pre class="mermaid"> tags
     * @returns {string} - Extracted Mermaid diagram content (without wrapper tags)
     * 
     * Purpose:
     * Extracts the most recent/last Mermaid diagram from a string that may contain
     * multiple diagrams in either markdown code blocks or HTML pre tags. This is
     * useful for getting the latest diagram when content is being streamed or updated.
     */
    
    // First try to extract from markdown code blocks
    const markdownRegex = /```mermaid(.*?)```/gis;
    const markdownMatches = [];
    let match;
    
    // Find positions of markdown matches
    while ((match = markdownRegex.exec(html)) !== null) {
        markdownMatches.push({
            position: match.index,
            content: match[1].trim()
        });
    }
    
    // Then try to extract from HTML pre tags
    const preTagRegex = /<pre\s+class=["']\s*mermaid\s*["']\s*>(.*?)<\/pre>/gis;
    const preTagMatches = [];
    
    // Reset regex lastIndex for second search
    preTagRegex.lastIndex = 0;
    
    // Find positions of pre tag matches
    while ((match = preTagRegex.exec(html)) !== null) {
        preTagMatches.push({
            position: match.index,
            content: match[1].trim()
        });
    }
    
    // Combine all matches and sort by position
    const allMatches = [...markdownMatches, ...preTagMatches];
    
    if (allMatches.length === 0) {
        return "";
    }
    
    // Sort by position and get the last match
    allMatches.sort((a, b) => a.position - b.position);
    const lastMatchContent = allMatches[allMatches.length - 1].content;
    
    // Validate that it contains Mermaid content (expanded detection)
    if (lastMatchContent && 
        (lastMatchContent.toLowerCase().includes("graph") ||
         lastMatchContent.toLowerCase().includes("flowchart") ||
         lastMatchContent.toLowerCase().includes("sequencediagram") ||
         lastMatchContent.toLowerCase().includes("gitgraph") ||
         lastMatchContent.toLowerCase().includes("classdiagram") ||
         lastMatchContent.toLowerCase().includes("statediagram") ||
         lastMatchContent.toLowerCase().includes("pie") ||
         lastMatchContent.toLowerCase().includes("journey") ||
         lastMatchContent.toLowerCase().includes("erdiagram"))) {
        
        // Clean up content by removing any remaining markdown markers
        return lastMatchContent.replace(/```mermaid/gi, "").replace(/```/g, "").trim();
    }
    
    return "";
}

// -----------------------------------------------------------------------------
// Mermaid / <details> open detection — module-level state
// All three variables are set inside renderMermaidIfDetailsTagOpened() which
// guards itself with _mermaidDetailsInitDone so they are populated exactly once.
// -----------------------------------------------------------------------------
var _mermaidDetailsInitDone = false;
var _mermaidAttrObserver = null;      // watches open-attr changes on known <details> nodes
var _mermaidNewDetailsObserver = null; // watches DOM for newly inserted <details> nodes

function renderMermaidIfDetailsTagOpened() {
    // Guard: register all listeners exactly once per page load.
    if (_mermaidDetailsInitDone) { return; }
    _mermaidDetailsInitDone = true;

    // Handler 1 — native 'toggle' event (spec-compliant, fires after open attr is set).
    // Namespaced so it can be cleanly removed via $(document).off('.mermaidDetails') if needed.
    $(document).on('toggle.mermaidDetails', 'details', function() {
        if (this.hasAttribute('open')) {
            // Small delay to ensure DOM is updated before running mermaid
            setTimeout(function() {
                normalizeMermaidBlocks(document);
                mermaid.run({querySelector: "pre.mermaid"});
            }, 50);
        }
    });

    // Handler 2 (MutationObserver) — attribute-change fallback for browsers / embedded
    // contexts where 'toggle' may not bubble reliably. Observes attributeFilter=['open']
    // only — no subtree scanning, no characterData — so it never fires on streamed text.
    if (typeof MutationObserver !== 'undefined') {
        _mermaidAttrObserver = new MutationObserver(function(mutations) {
            mutations.forEach(function(mutation) {
                if (mutation.attributeName === 'open' &&
                    mutation.target.tagName.toLowerCase() === 'details' &&
                    mutation.target.hasAttribute('open')) {
                    setTimeout(function() {
                        normalizeMermaidBlocks(document);
                        mermaid.run({querySelector: "pre.mermaid"});
                    }, 50);
                }
            });
        });

        // Wire up all <details> elements already in the DOM at init time.
        document.querySelectorAll('details').forEach(function(el) {
            _mermaidAttrObserver.observe(el, { attributes: true, attributeFilter: ['open'] });
        });

        // Handler 3 — watch for NEW <details> inserted during streaming.
        // Replaces the deprecated synchronous DOMNodeInserted event, which was firing
        // on every single DOM write during streaming and blocking the rendering pipeline.
        // MutationObserver fires asynchronously after each task, never mid-mutation.
        _mermaidNewDetailsObserver = new MutationObserver(function(mutations) {
            mutations.forEach(function(mutation) {
                mutation.addedNodes.forEach(function(node) {
                    if (node.nodeType !== 1) { return; } // element nodes only
                    // Direct match: the added node is itself a <details>
                    if (node.tagName.toLowerCase() === 'details') {
                        _mermaidAttrObserver.observe(node, { attributes: true, attributeFilter: ['open'] });
                    }
                    // Descendants: a whole message card (or subtree) may contain <details> inside it.
                    // Early-exit if no children to avoid querySelectorAll on leaf nodes.
                    if (node.children && node.children.length > 0) {
                        node.querySelectorAll('details').forEach(function(el) {
                            _mermaidAttrObserver.observe(el, { attributes: true, attributeFilter: ['open'] });
                        });
                    }
                });
            });
        });
        _mermaidNewDetailsObserver.observe(document.body, { childList: true, subtree: true });
    }
}



function copyToClipboard(textElem, textToCopy, mode = "text") {  
    // Handle CodeMirror editor specifically  
    if (mode === "codemirror") {  
        // Check if it's CodeMirror 5 or 6  
        if (textElem && typeof textElem.getValue === 'function') {  
            // CodeMirror 5 API  
            textToCopy = textElem.getValue();  
            // [DEBUG] console.log("📋 Using CodeMirror 5 API for copy");  
        } else if (textElem && textElem.state && textElem.state.doc) {  
            // CodeMirror 6 API  
            textToCopy = textElem.state.doc.toString();  
            // [DEBUG] console.log("📋 Using CodeMirror 6 API for copy");  
        } else {  
            console.error("❌ Invalid CodeMirror editor instance:", textElem);  
            showToast("Failed to access editor content", "error");  
            return false;  
        }  
    }  
    // Your existing logic for other modes  
    else if (mode === "text") {  
        var textElements = $(textElem);  
    }  
    else if (mode === "code") {  
        var textElements = $(textElem).closest('.code-block').find('code');  
    }  
    else {  
        var textElements = $(textElem).find('p, span, div, code, h1, h2, h3, h4, h5, h6, strong, em, input');  
    }  
  
    // if textToCopy is undefined, then we will copy the text from the textElem  
    if (textToCopy === undefined && mode !== "codemirror") {  
        var textToCopy = "";  
        textElements.each(function () {  
            var $this = $(this);  
            if ($this.is("input, textarea")) {  
                textToCopy += $this.val().replace(/\\\[show\\]|\\\[hide\\\]/g, '') + "\n";  
            } else {  
                textToCopy += $this.text().replace(/\\\[show\\\]|\\\[hide\\\]/g, '') + "\n";  
            }  
        });  
    }  

    // Guard clipboard output for Mermaid/code-like text
    textToCopy = normalizeTextForClipboard(textElem, textToCopy, mode);
  
    if (navigator.clipboard && navigator.clipboard.writeText) {  
        // New Clipboard API  
        navigator.clipboard.writeText(textToCopy).then(() => {  
            // [DEBUG] console.log("✅ Text successfully copied to clipboard");  
            showToast("Code copied to clipboard!", "success");  
        }).catch(err => {  
            console.warn("⚠️ Copy to clipboard failed.", err);  
            showToast("Failed to copy code", "error");  
        });  
    } else {  
        // Fallback to the older method for incompatible browsers  
        var textarea = document.createElement("textarea");  
        textarea.textContent = textToCopy;  
        document.body.appendChild(textarea);  
        textarea.select();  
        try {  
            var success = document.execCommand("copy");  
            if (success) {  
                showToast("Code copied to clipboard!", "success");  
            }  
            return success;  
        } catch (ex) {  
            console.warn("⚠️ Copy to clipboard failed.", ex);  
            showToast("Failed to copy code", "error");  
            return false;  
        } finally {  
            document.body.removeChild(textarea);  
        }  
    }  
}  

  
// Simple toast notification function  
function showToast(message, type = "info") {  
    // You can integrate with your existing notification system  
    // For now, using a simple alert - replace with your toast system  
    console.log(`${type.toUpperCase()}: ${message}`);  
    // Example with Bootstrap toast (if you have it):  
    // $('.toast-body').text(message);  
    // $('.toast').toast('show');  
}  




function getOptions(parentElementId, type) {
    checkBoxOptionOne = "googleScholar"
    optionOneChecked = $(type === "assistant" ? `#${parentElementId}-${type}-use-google-scholar` : `#${parentElementId}-${type}-use-references-and-citations-checkbox`).is(':checked');
    slow_fast = `${parentElementId}-${type}-provide-detailed-answers-checkbox`
    values = {
        perform_web_search: $(`#${parentElementId}-${type}-perform-web-search-checkbox`).length ? $(`#${parentElementId}-${type}-perform-web-search-checkbox`).is(':checked') : $('#settings-perform-web-search-checkbox').is(':checked'),
        use_multiple_docs: $(`#${parentElementId}-${type}-use-multiple-docs-checkbox`).length ? $(`#${parentElementId}-${type}-use-multiple-docs-checkbox`).is(':checked') : false,
        tell_me_more: $(`#${parentElementId}-${type}-tell-me-more-checkbox`).length ? $(`#${parentElementId}-${type}-tell-me-more-checkbox`).is(':checked') : false,
        use_memory_pad: $('#use_memory_pad').length ? $('#use_memory_pad').is(':checked') : $('#settings-use_memory_pad').is(':checked'),
        enable_planner: $('#enable_planner').length ? $('#enable_planner').is(':checked') : $('#settings-enable_planner').is(':checked'),
        search_exact: $(`#${parentElementId}-${type}-search-exact`).length ? $(`#${parentElementId}-${type}-search-exact`).is(':checked') : $('#settings-search-exact').is(':checked'),
        ensemble: $(`#${parentElementId}-${type}-ensemble`).length ? $(`#${parentElementId}-${type}-ensemble`).is(':checked') : false,
        auto_clarify: $(`#${parentElementId}-${type}-auto_clarify`).length ? $(`#${parentElementId}-${type}-auto_clarify`).is(':checked') : ($('#settings-auto_clarify').length ? $('#settings-auto_clarify').is(':checked') : false),
        persist_or_not: $(`#${parentElementId}-${type}-persist_or_not`).length ? $(`#${parentElementId}-${type}-persist_or_not`).is(':checked') : $('#settings-persist_or_not').is(':checked'),
        ppt_answer: $('#settings-ppt-answer').is(':checked'),
        render_slides_inline: $('#settings-render-slides-inline').is(':checked'),
        only_slides: $('#settings-only-slides').is(':checked'),
        render_close_to_source: $('#settings-render-close-to-source').is(':checked'),
        use_pkb: $('#settings-use_pkb').length ? $('#settings-use_pkb').is(':checked') : true,
        opencode_enabled: $('#settings-enable_opencode').length ? $('#settings-enable_opencode').is(':checked') : false,
        enable_tool_use: $('#settings-tool_mode').length ? ($('#settings-tool_mode').val() !== 'none') : false,
        tool_mode: $('#settings-tool_mode').length ? $('#settings-tool_mode').val() : 'hybrid',
        auto_doubts_enabled: $('#settings-auto_doubts_enabled').length ? $('#settings-auto_doubts_enabled').is(':checked') : false,
        enabled_tools: (function() {
            var $sel = $('#settings-tool-selector');
            if (!$sel.length) return [];
            if (typeof $.fn.selectpicker !== 'undefined' && $sel.data('selectpicker')) {
                $sel.selectpicker('refresh');
                return $sel.selectpicker('val') || [];
            }
            return $sel.val() || [];
        })(),
    };
    let speedValue = $("#depthSelector").length ? $("#depthSelector").val() : ($("#settings-depthSelector").val() || '2');
    values['provide_detailed_answers'] = speedValue;
    values[checkBoxOptionOne] = optionOneChecked;
    if (type === "assistant") {
        let historyValue = $("#historySelector").length ? $("#historySelector").val() : ($("#settings-historySelector").val() || '2');
        values['enable_previous_messages'] = historyValue;
        let rewardLevelValue = $("#rewardLevelSelector").length ? $("#rewardLevelSelector").val() : ($("#settings-rewardLevelSelector").val() || '0');
        values['reward_level'] = rewardLevelValue;
    }
    
    if (type === "assistant") {
        // Get preamble options, including custom ones
        let preambleOptions = $('#preamble-selector').length ? 
            $('#preamble-selector').val() : 
            $('#settings-preamble-selector').val();
        
        // If modal hasn't been opened and no value found, check persisted state
        if (!preambleOptions && window.chatSettingsState) {
            preambleOptions = window.chatSettingsState.preamble_options;
        }
        
        values['preamble_options'] = preambleOptions || [];
        // Use tracked selection order if available (first selected = primary for diff)
        var _modelVal = $('#main-model-selector').length ? $('#main-model-selector').val() : $('#settings-main-model-selector').val();
        if (window._modelSelectionOrder && window._modelSelectionOrder.length > 1) {
            _modelVal = window._modelSelectionOrder;
        }
        values['main_model'] = _modelVal;
        values['field'] = $('#field-selector').length ? $('#field-selector').val() : $('#settings-field-selector').val();
        values["permanentText"] = $("#permanentText").length ? $("#permanentText").val() : $("#settings-permanentText").val();
        if (window.chatSettingsState && window.chatSettingsState.model_overrides) {
            values['model_overrides'] = window.chatSettingsState.model_overrides;
        }
    }
    return values
}



function isAbsoluteUrl(url) {
    // A simple way to check if the URL is absolute is by looking for the presence of '://'
    return url.indexOf('://') > 0;
};


function apiCall(url, method, data, useFetch = false) {
    //     url = appendKeyStore(url);

    if (useFetch) {
        const options = {
            method: method,
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(data),
        };

        if (method === 'GET') {
            delete options.body;
        }
        let response = fetch(url, options);
        responseWaitAndSuccessChecker(url, response);
        return response
    } else {
        if (method === 'GET') {
            return $.get(url, data);
        } else if (method === 'POST') {
            return $.post({ url: url, data: JSON.stringify(data), contentType: 'application/json' });
        } else if (method === 'DELETE') {
            return $.ajax({
                url: url,
                type: 'DELETE'
            });
        }
        // Add other methods as needed
    }
}

function showPDF(pdfUrl, subtree, url=null) {
    var parent_of_view = document.getElementById(`${subtree}`);
    var xhr = new XMLHttpRequest();
    var progressBar = parent_of_view.querySelector('#progressbar');
    var progressStatus = parent_of_view.querySelector('#progress-status');
    var viewer = parent_of_view.querySelector("#pdfjs-viewer");
    progressBar.style.width = '0%';
    progressStatus.textContent = '';
    viewer.style.display = 'none';  // Hide the viewer while loading
    document.getElementById('progress').style.display = 'block';  // Show the progress bar

    if (url) {
        xhr.open('GET', `${url}?file=` + encodeURIComponent(pdfUrl), true);
    } else {
        xhr.open('GET', '/proxy?file=' + encodeURIComponent(pdfUrl), true);
    }
    
    xhr.responseType = 'blob';

    // Track progress
    xhr.onprogress = function (e) {
        document.getElementById('progress').style.display = 'block';
        if (e.lengthComputable) {
            var percentComplete = (e.loaded / e.total) * 100;
            progressStatus.style.display = 'block'; // Hide the progress status
            progressBar.style.display = 'block';
            progressBar.style.width = percentComplete + '%';
            progressStatus.textContent = 'Downloaded ' + (e.loaded / 1024).toFixed(2) + ' of ' + (e.total / 1024).toFixed(2) + ' KB (' + Math.round(percentComplete) + '%)';
        } else {
            progressStatus.style.display = 'block'; // Hide the progress status
            progressStatus.textContent = 'Downloaded ' + (e.loaded / 1024).toFixed(2) + ' KB';
        }
    }


    xhr.onload = function (e) {


        if (this.status == 200) {
            var blob = this.response;

            // Create an object URL for the Blob
            var objectUrl = URL.createObjectURL(blob);

            // Reset the src of the viewer
            viewer.setAttribute('src', viewer.getAttribute('data-original-src'));

            // Construct the full URL to the PDF
            var viewerUrl = viewer.getAttribute('src') + '?file=' + encodeURIComponent(objectUrl);

            // Load the PDF into the viewer
            viewer.setAttribute('src', viewerUrl);

            function resizePdfView(event) {
                var width = $('#content-col').width();
                var height = ($("#pdf-questions").is(':hidden') || $("#pdf-questions").length === 0) ? $(window).height() : $(window).height() * 0.8;
                $('#pdf-content').css({
                    'width': width,
                });
                $(viewer).css({
                    'width': '100%',
                    'height': height,
                });
            }

            $(window).resize(resizePdfView).trigger('resize'); // trigger resize event after showing the PDF

            viewer.style.display = 'block';  // Show the viewer once the PDF is ready
            document.getElementById('progress').style.display = 'none';  // Hide the progress bar
            progressStatus.style.display = 'none'; // Hide the progress status
            progressBar.style.display = 'none';
        } else {
            console.error("Error occurred while fetching PDF: " + this.status);
        }
    };

    xhr.send();
}

function pdfTabIsActive() {
    if ($("#pdf-tab").hasClass("active")) {
        // If it is, show the elements
        $("#hide-navbar").parent().show();
        $("#toggle-tab-content").parent().show();
        $("#details-tab").parent().show();
    } else {
        // If it's not, hide the elements
        $("#hide-navbar").parent().hide();
        $("#toggle-tab-content").parent().hide();
        $("#details-tab").parent().hide();
    }
}

/**
 * Initialize Reveal.js for slide presentations within a container
 * @param {jQuery} container - The container element containing the slide presentation
 */
function initializeSlidePresentation(container) {
    try {
        // Find the slide presentation wrapper
        var slideWrapper = container.find('.slide-presentation-wrapper');
        if (slideWrapper.length === 0) {
            console.error('Slide presentation wrapper not found');
            return;
        }
        
        var slideId = slideWrapper.attr('id');
        if (!slideId) {
            console.error('Slide presentation wrapper has no ID');
            return;
        }
        // Already initialized
        if (slideWrapper.data('revealInstance')) {
            return;
        }
        
        // Check if Reveal.js is available
        if (typeof Reveal === 'undefined') {
            // Item 7: Reveal.js is lazy-loaded. Load it, then retry.
            if (typeof LazyLibs !== 'undefined') {
                LazyLibs.loadReveal().then(function () {
                    initializeSlidePresentation(container);
                }).catch(function (err) {
                    console.error('Failed to load Reveal.js:', err);
                });
            } else {
                console.error('Reveal.js is not loaded and LazyLibs is unavailable');
            }
            return;
        }
        
        // Find the reveal container within the slide wrapper
        var revealContainer = slideWrapper.find('.reveal');
        if (revealContainer.length === 0) {
            console.error('Reveal container not found in slide presentation');
            return;
        }
        
        // Initialize Reveal.js for this specific container
        // Create a new Reveal instance for this specific container
        var revealInstance = new Reveal(revealContainer[0], {
            embedded: true,
            hash: false,
            controls: true,
            progress: true,
            center: false,
            transition: 'slide',
            backgroundTransition: 'fade',
            plugins: [RevealHighlight, RevealMath.KaTeX]
        });
        
        revealInstance.initialize().then(function() {
            // [DEBUG] console.log('Reveal.js initialized successfully for slide presentation');
            
            // Add navigation controls if they don't exist
            addSlideNavigationControls(slideWrapper);
            
            // Update slide counter on slide change
            revealInstance.on('slidechanged', function(event) {
                updateSlideCounter(slideWrapper, event.indexh + 1);
                // Re-adjust card height if slide content changes
                setTimeout(function() {
                    adjustCardHeightForSlides(slideWrapper);
                }, 50);
            });
            
            // Initialize slide counter
            var totalSlides = revealInstance.getTotalSlides();
            updateSlideCounter(slideWrapper, 1, totalSlides);
            
            // Store the reveal instance on the wrapper for later use
            slideWrapper.data('revealInstance', revealInstance);
            
            // Ensure the Bootstrap card grows enough to contain the slides
            setTimeout(function() {
                adjustCardHeightForSlides(slideWrapper);
                // [DEBUG] console.log('Initial card height adjustment completed');
            }, 100);
            
            // Also adjust on window resize
            var resizeHandler = function() { 
                setTimeout(function() {
                    adjustCardHeightForSlides(slideWrapper);
                }, 100);
            };
            slideWrapper.data('resizeHandler', resizeHandler);
            $(window).on('resize', resizeHandler);
            
        }).catch(function(error) {
            console.error('Error initializing Reveal.js:', error);
        });
        
    } catch (error) {
        console.error('Error in initializeSlidePresentation:', error);
    }
}

/**
 * Add navigation controls to slide presentation
 * @param {jQuery} slideWrapper - The slide wrapper element
 */
function addSlideNavigationControls(slideWrapper) {
    // Check if controls already exist
    if (slideWrapper.find('.slide-controls').length > 0) {
        return;
    }
    
    var controlsHtml = `
        <div class="slide-controls mt-3 d-flex justify-content-between align-items-center">
            <button class="btn btn-sm btn-outline-primary slide-prev-btn">
                <i class="bi bi-chevron-left"></i> Previous
            </button>
            <span class="slide-counter-display mx-3">
                <span class="current-slide">1</span> / <span class="total-slides">1</span>
            </span>
            <button class="btn btn-sm btn-outline-primary slide-next-btn">
                Next <i class="bi bi-chevron-right"></i>
            </button>
        </div>
    `;
    
    slideWrapper.append(controlsHtml);
    
    // Add event listeners for navigation buttons
    slideWrapper.find('.slide-prev-btn').on('click', function() {
        var revealInstance = slideWrapper.data('revealInstance');
        if (revealInstance) {
            revealInstance.prev();
        }
    });
    
    slideWrapper.find('.slide-next-btn').on('click', function() {
        var revealInstance = slideWrapper.data('revealInstance');
        if (revealInstance) {
            revealInstance.next();
        }
    });
}

/**
 * Update slide counter display
 * @param {jQuery} slideWrapper - The slide wrapper element
 * @param {number} current - Current slide number (1-based)
 * @param {number} total - Total number of slides (optional)
 */
function updateSlideCounter(slideWrapper, current, total) {
    var currentSlideSpan = slideWrapper.find('.current-slide');
    var totalSlidesSpan = slideWrapper.find('.total-slides');
    
    if (currentSlideSpan.length > 0) {
        currentSlideSpan.text(current);
    }
    
    if (total !== undefined && totalSlidesSpan.length > 0) {
        totalSlidesSpan.text(total);
    }
}

/**
 * Ensure the Bootstrap card is tall enough to fully display slides
 * @param {jQuery} slideWrapper - The slide wrapper element
 */
function adjustCardHeightForSlides(slideWrapper) {
    try {
        var cardBody = slideWrapper.closest('.card-body');
        if (!cardBody.length) { 
            // [DEBUG] console.log('No card-body found for slide adjustment');
            return; 
        }
        
        // Mark the message card as having slides
        var messageCard = cardBody.closest('.card.message-card');
        if (messageCard.length) {
            messageCard.addClass('has-slides');
            // [DEBUG] console.log('Added has-slides class to message card');
        }
        
        // Calculate desired height: slide container height + controls + padding
        var wrapperHeight = slideWrapper.outerHeight(true) || 560;
        var controls = slideWrapper.find('.slide-controls');
        var controlsHeight = controls.length ? controls.outerHeight(true) : 40;
        var desired = Math.max(600, wrapperHeight + controlsHeight + 40);
        
        // [DEBUG] console.log('Adjusting card height - wrapper:', wrapperHeight, 'controls:', controlsHeight, 'desired:', desired);
        
        // Apply min-height and ensure no clipping
        cardBody.css({ 
            'min-height': desired + 'px', 
            'overflow': 'visible',
            'height': 'auto'
        });
        
        // Also ensure the message container allows growth
        if (messageCard.length) {
            messageCard.css({ 
                'overflow': 'visible',
                'min-height': (desired + 20) + 'px',
                'height': 'auto'
            });
        }
        
        // Force a layout recalculation
        setTimeout(function() {
            if (slideWrapper.data('revealInstance')) {
                slideWrapper.data('revealInstance').layout();
            }
        }, 100);
        
    } catch (error) {
        console.error('Error adjusting card height for slides:', error);
    }
}

/**
 * Register the Service Worker for the `/interface/*` UI shell.
 *
 * Notes:
 * - Service Workers require HTTPS (localhost is allowed).
 * - Scope is intentionally limited to `/interface/` so we do not interfere with API routes.
 * - Any failures must be non-fatal for the UI.
 */
(function registerInterfaceServiceWorker() {
    try {
        if (!('serviceWorker' in navigator)) return;
        var isLocalhost = (location.hostname === 'localhost' || location.hostname === '127.0.0.1');
        if (location.protocol !== 'https:' && !isLocalhost) return;

        navigator.serviceWorker
            .register('/interface/service-worker.js', { scope: '/interface/' })
            .then(function(reg) {
                if (reg.waiting) {
                    reg.waiting.postMessage({ type: 'SKIP_WAITING' });
                }
                reg.addEventListener('updatefound', function() {
                    var newWorker = reg.installing;
                    if (!newWorker) return;
                    newWorker.addEventListener('statechange', function() {
                        if (newWorker.state === 'installed' && reg.active) {
                            newWorker.postMessage({ type: 'SKIP_WAITING' });
                        }
                    });
                });
            })
            .catch(function (err) {
                console.warn('Service Worker registration failed:', err);
            });

        navigator.serviceWorker.addEventListener('controllerchange', function() {
            window.location.reload();
        });
    } catch (e) {
        // Non-fatal: never block UI boot.
        console.warn('Service Worker registration error:', e);
    }
})();

/**
 * Clear all Service Worker caches and unregister the SW.
 * Calls the server endpoint first, then performs client-side cleanup.
 * Returns a Promise that resolves when cleanup is complete.
 */
function clearSwCaches() {
    var tasks = [];

    if ('caches' in window) {
        tasks.push(
            caches.keys().then(function(names) {
                return Promise.all(names.map(function(name) {
                    // [DEBUG] console.log('[clearSwCaches] deleting cache:', name);
                    return caches.delete(name);
                }));
            })
        );
    }

    if ('serviceWorker' in navigator) {
        tasks.push(
            navigator.serviceWorker.getRegistrations().then(function(regs) {
                return Promise.all(regs.map(function(reg) {
                    // [DEBUG] console.log('[clearSwCaches] unregistering SW:', reg.scope);
                    return reg.unregister();
                }));
            })
        );
    }

    // Clear the rendered-HTML snapshot store (IndexedDB). This is NOT covered by
    // the Cache API above, so without this a logout/login still restores stale
    // per-conversation rendered markup (e.g. a message edit appearing to revert).
    try {
        if (window.RenderedStateManager && window.RenderedStateManager.clearAll) {
            tasks.push(Promise.resolve(window.RenderedStateManager.clearAll()));
        } else if ('indexedDB' in window && indexedDB.deleteDatabase) {
            tasks.push(new Promise(function(resolve) {
                try {
                    var req = indexedDB.deleteDatabase('science-chat-rendered-state');
                    req.onsuccess = req.onerror = req.onblocked = function() { resolve(); };
                } catch (_e) { resolve(); }
            }));
        }
    } catch (_e) { /* best-effort */ }

    // Clear the in-memory ConversationUIState cache (section collapse / message
    // show-hide state from the prior user session).
    try {
        if (window.ConversationUIState && typeof window.ConversationUIState.clear === 'function') {
            window.ConversationUIState.clear();
        }
    } catch (_e) { /* best-effort */ }

    // Clear localStorage and sessionStorage to avoid leaking user preferences
    // (chat settings, sidebar state, auto-scroll pref, etc.) across sessions.
    try { localStorage.clear(); } catch (_e) { /* best-effort */ }
    try { sessionStorage.clear(); } catch (_e) { /* best-effort */ }

    return Promise.all(tasks)
        .then(function() { /* [DEBUG] console.log('[clearSwCaches] all caches cleared'); */ })
        .catch(function(err) { console.warn('[clearSwCaches] error:', err); });
}
