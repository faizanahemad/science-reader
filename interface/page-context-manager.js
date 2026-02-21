/**
 * PageContextManager - Manages extracted page context for the chat send flow.
 * Provides a collapsible panel showing extracted content and formats it
 * for the backend payload via getPageContextForPayload().
 */
var PageContextManager = (function() {
    'use strict';

    var P = '[PageCtxMgr]';
    // console.log(P, '=== MODULE LOADING ===');

    var SINGLE_CONTENT_LIMIT = 64000;
    var MULTI_CONTENT_LIMIT = 128000;

    var _context = null;
    var _expanded = false;

    function _truncate(text, limit) {
        if (!text || text.length <= limit) return text;
        return text.substring(0, limit) + '\n\n[Content truncated at ' + limit + ' characters]';
    }

    function _countWords(text) {
        if (!text) return 0;
        return text.trim().split(/\s+/).filter(Boolean).length;
    }

    function _formatCount(n) {
        return n.toLocaleString();
    }

    function _ocrSingleScreenshot(dataUrl, url, title) {
        return $.ajax({
            url: '/ext/ocr',
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ images: [dataUrl], url: url, title: title }),
            timeout: 120000
        }).then(function(result) {
            return result && result.text ? result.text : '';
        }).catch(function() {
            return '';
        });
    }

    function _captureAndOcrPipelined(tabId) {
        var ocrPromises = [];
        var capturedCount = 0;
        var pageUrl = '';
        var pageTitle = '';

        var progressHandler = function(progress) {
            if (progress && progress.screenshot && progress.tabId === tabId) {
                capturedCount++;
                pageUrl = progress.pageUrl || pageUrl;
                pageTitle = progress.pageTitle || pageTitle;
                var pageIndex = progress.pageIndex || (capturedCount - 1);
                if (typeof showToast === 'function') {
                    showToast('Capturing ' + capturedCount + '/' + (progress.total || '?') + ' (OCR pipelining...)', 'info');
                }
                var ocrP = _ocrSingleScreenshot(progress.screenshot, pageUrl, pageTitle).then(function(text) {
                    return { index: pageIndex, text: text };
                });
                ocrPromises.push(ocrP);
            }
        };

        ExtensionBridge.onProgress(progressHandler);

        return ExtensionBridge.captureFullPageWithOcr(tabId, {})
            .then(function(meta) {
                return Promise.all(ocrPromises).then(function(results) {
                    results.sort(function(a, b) { return a.index - b.index; });
                    var combinedText = results
                        .filter(function(r) { return r.text; })
                        .map(function(r) { return r.text; })
                        .join('\n\n--- PAGE ---\n\n');
                    var pages = results.map(function(r) { return { index: r.index, text: r.text }; });
                    return {
                        url: meta.pageUrl || pageUrl,
                        title: meta.pageTitle || pageTitle,
                        content: combinedText,
                        isOcr: true,
                        ocrPagesData: pages,
                        tabId: tabId
                    };
                });
            });
    }

    function _updatePanel() {
        if (!_context) {
            $('#page-context-panel').hide();
            return;
        }
        $('#page-context-panel').show();

        var title = _context.title || 'Untitled';
        var url = _context.url || '';
        var isMulti = _context.isMultiTab || false;
        var tabCount = _context.tabCount || 1;
        var content = _context.content || '';
        var words = _countWords(content);

        var badge = '';
        if (isMulti) {
            badge = tabCount + ' tabs | ' + _formatCount(words) + ' words';
        } else {
            badge = _formatCount(words) + ' words';
        }
        if (_context.isOcr) badge += ' (OCR)';
        $('#page-context-count').text(badge).show();

        var preview = '';
        if (isMulti && _context.sources && _context.sources.length > 0) {
            _context.sources.forEach(function(src) {
                var srcWords = _countWords(src.content || '');
                var srcChars = src.contentLength || (src.content || '').length;
                preview += '• ' + (src.title || 'Untitled') + ' (' + _formatCount(srcWords) + ' words)\n';
            });
        } else {
            preview = title + '\n' + url + '\n' + _formatCount(words) + ' words | ' + _formatCount(content.length) + ' chars\n\n';
            preview += content.length > 500 ? content.substring(0, 500) + '…' : content;
        }
        $('#page-context-body').text(preview);
    }

    function _bindEvents() {
        // Debug logging commented out — re-enable for _bindEvents debugging
        // console.log(P, '_bindEvents called');
        // console.log(P, '  #ext-extract-page exists:', $('#ext-extract-page').length > 0);
        // console.log(P, '  #ext-refresh-page exists:', $('#ext-refresh-page').length > 0);
        // console.log(P, '  #ext-multi-tab exists:', $('#ext-multi-tab').length > 0);
        // console.log(P, '  .ext-btn count:', $('.ext-btn').length);
        // console.log(P, '  .ext-btn display values:', $('.ext-btn').map(function(){ return this.id + '=' + $(this).css('display'); }).get().join(', '));
        // console.log(P, '  #page-context-panel exists:', $('#page-context-panel').length > 0);
        // console.log(P, '  #page-context-clear exists:', $('#page-context-clear').length > 0);
        // console.log(P, '  #page-context-toggle exists:', $('#page-context-toggle').length > 0);
        // console.log(P, '  #page-context-refresh exists:', $('#page-context-refresh').length > 0);
        // console.log(P, '  #page-context-view exists:', $('#page-context-view').length > 0);

        $('#page-context-view').on('click', function() {
            if (_context && typeof ContentViewer !== 'undefined') {
                ContentViewer.show(_context);
            }
        });

        $('#page-context-clear').on('click', function() {
            _context = null;
            _expanded = false;
            _updatePanel();
        });

        $('#page-context-toggle').on('click', function() {
            _expanded = !_expanded;
            if (_expanded) {
                $('#page-context-body').slideDown(150);
                $('#page-context-toggle i').removeClass('fa-chevron-down').addClass('fa-chevron-up');
            } else {
                $('#page-context-body').slideUp(150);
                $('#page-context-toggle i').removeClass('fa-chevron-up').addClass('fa-chevron-down');
            }
        });

        $('#page-context-refresh').on('click', function() {
            if (!ExtensionBridge.isAvailable) {
                if (typeof showToast === 'function') showToast('Extension not available', 'warning');
                return;
            }
            var $btn = $(this);
            $btn.find('i').addClass('fa-spin');

            if (_context && _context.isMultiTab && _context.sources && _context.sources.length > 0) {
                // Multi-tab: invalidate cache for all sources, then re-extract each by tabId in parallel
                var sources = _context.sources;
                sources.forEach(function(src) {
                    if (src.url) ExtensionBridge.cacheInvalidate(src.url).catch(function() {});
                });
                var promises = sources.map(function(src) {
                    return ExtensionBridge.extractTab(src.tabId).catch(function(err) {
                        console.warn('[PageCtxMgr] page-context-refresh: extractTab failed for', src.url, err);
                        // Return the stale source content so we don't drop the tab entirely
                        return { tabId: src.tabId, url: src.url, title: src.title, content: src.content };
                    });
                });
                Promise.all(promises).then(function(results) {
                    PageContextManager.setMultiTabContext(results);
                    if (typeof showToast === 'function') showToast('All tabs refreshed (' + results.length + ')', 'success');
                }).catch(function(err) {
                    if (typeof showToast === 'function') showToast('Refresh failed: ' + (err.message || err), 'danger');
                }).finally(function() {
                    $btn.find('i').removeClass('fa-spin');
                });
            } else {
                // Single page: invalidate cache and re-extract current page
                if (_context && _context.url) {
                    ExtensionBridge.cacheInvalidate(_context.url).catch(function() {});
                }
                ExtensionBridge.extractCurrentPage().then(function(data) {
                    PageContextManager.setSingleContext(data);
                    if (typeof showToast === 'function') showToast('Page context refreshed', 'success');
                }).catch(function(err) {
                    if (typeof showToast === 'function') showToast('Refresh failed: ' + (err.message || err), 'danger');
                }).finally(function() {
                    $btn.find('i').removeClass('fa-spin');
                });
            }
        });

        $('#ext-extract-page').on('click', function() {
            var $btn = $(this);
            $btn.prop('disabled', true).find('i').removeClass('fa-globe').addClass('fa-spinner fa-spin');
            ExtensionBridge.extractCurrentPage().then(function(data) {
                PageContextManager.setSingleContext(data);
                var msg = data.cached ? 'Page content extracted (cached)' : 'Page content extracted';
                if (typeof showToast === 'function') showToast(msg, 'success');
            }).catch(function(err) {
                if (typeof showToast === 'function') showToast('Extraction failed: ' + (err.message || err), 'danger');
            }).finally(function() {
                $btn.prop('disabled', false).find('i').removeClass('fa-spinner fa-spin').addClass('fa-globe');
            });
        });

        $('#ext-refresh-page').on('click', function() {
            if (!ExtensionBridge.isAvailable) {
                if (typeof showToast === 'function') showToast('Extension not available', 'warning');
                return;
            }
            var $btn = $(this);
            $btn.prop('disabled', true).find('i').addClass('fa-spin');
            // Invalidate cache before re-extracting so refresh always fetches fresh content
            if (_context && _context.url) {
                ExtensionBridge.cacheInvalidate(_context.url).catch(function() {});
            } else if (_context && _context.isMultiTab && _context.sources) {
                _context.sources.forEach(function(src) {
                    if (src.url) ExtensionBridge.cacheInvalidate(src.url).catch(function() {});
                });
            }
            ExtensionBridge.extractCurrentPage().then(function(data) {
                PageContextManager.setSingleContext(data);
                if (typeof showToast === 'function') showToast('Page context refreshed', 'success');
            }).catch(function(err) {
                if (typeof showToast === 'function') showToast('Refresh failed: ' + (err.message || err), 'danger');
            }).finally(function() {
                $btn.prop('disabled', false).find('i').removeClass('fa-spin');
            });
        });

        $('#ext-multi-tab').on('click', function() {
            if (typeof TabPickerManager !== 'undefined') {
                TabPickerManager.show();
            }
        });
    }

    return {
        init: function() {
            // console.log(P, 'init() called');
            // console.log(P, 'ExtensionBridge exists:', typeof ExtensionBridge !== 'undefined');
            // console.log(P, 'ExtensionBridge.isAvailable:', typeof ExtensionBridge !== 'undefined' ? ExtensionBridge.isAvailable : 'N/A');
            _bindEvents();
            // console.log(P, 'init() done');
        },

        hasContext: function() {
            return _context !== null;
        },

        setSingleContext: function(data) {
            var content = (data.content || data.text || '');
            var words = _countWords(content);
            console.log(P, 'setSingleContext:', data.title, '|', content.length, 'chars |', words, 'words');
            _context = {
                url: data.url || '',
                title: data.title || '',
                content: _truncate(content, SINGLE_CONTENT_LIMIT),
                screenshot: data.screenshot || null,
                isScreenshot: data.isScreenshot || false,
                isMultiTab: false,
                tabCount: 1,
                isOcr: data.isOcr || false,
                sources: [],
                ocrPagesData: data.ocrPagesData || [],
                mergeType: 'single',
                wordCount: words,
                charCount: content.length,
                lastRefreshed: Date.now()
            };
            _updatePanel();
        },

        setMultiTabContext: function(results) {
            if (!results || results.length === 0) return;

            var sources = [];
            var mergedContent = '';
            var hasOcr = false;

            results.forEach(function(tab) {
                var tabContent = tab.content || tab.text || '';
                sources.push({
                    tabId: tab.tabId,
                    url: tab.url || '',
                    title: tab.title || '',
                    content: tabContent,
                    contentLength: tabContent.length,
                    wordCount: _countWords(tabContent)
                });
                mergedContent += '## Tab: ' + (tab.title || 'Untitled') + '\n';
                mergedContent += 'URL: ' + (tab.url || '') + '\n\n';
                mergedContent += tabContent + '\n\n---\n\n';
                if (tab.isOcr || tab.ocrPagesData) hasOcr = true;
            });

            var totalWords = _countWords(mergedContent);
            console.log(P, 'setMultiTabContext:', sources.length, 'tabs |', mergedContent.length, 'chars |', totalWords, 'words');

            _context = {
                url: sources[0].url,
                title: sources.length + ' tabs captured',
                content: _truncate(mergedContent, MULTI_CONTENT_LIMIT),
                screenshot: null,
                isScreenshot: false,
                isMultiTab: true,
                tabCount: sources.length,
                isOcr: hasOcr,
                sources: sources,
                ocrPagesData: [],
                mergeType: 'multi_tab',
                wordCount: totalWords,
                charCount: mergedContent.length,
                lastRefreshed: Date.now()
            };
            _updatePanel();
        },

        getPageContextForPayload: function() {
            if (!_context) return null;
            return {
                url: _context.url,
                title: _context.title,
                content: _context.content,
                screenshot: _context.screenshot,
                isScreenshot: _context.isScreenshot,
                isMultiTab: _context.isMultiTab,
                tabCount: _context.tabCount,
                isOcr: _context.isOcr,
                sources: _context.sources,
                ocrPagesData: _context.ocrPagesData,
                mergeType: _context.mergeType,
                wordCount: _context.wordCount,
                charCount: _context.charCount,
                lastRefreshed: _context.lastRefreshed
            };
        },

        getContext: function() {
            return _context;
        },

        capturePageWithOcr: function(tabId) {
            return _captureAndOcrPipelined(tabId).then(function(data) {
                PageContextManager.setSingleContext(data);
                if (typeof showToast === 'function') {
                    showToast('OCR extraction complete: ' + _formatCount(_countWords(data.content)) + ' words', 'success');
                }
                return data;
            });
        },

        clear: function() {
            _context = null;
            _expanded = false;
            _updatePanel();
        }
    };
})();

$(document).ready(function() {
    // console.log('[PageCtxMgr]', '$(document).ready fired — calling PageContextManager.init()');
    PageContextManager.init();
});
