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

    /**
     * Resolve the tabId of the currently active non-UI tab via the extension.
     * Used by OCR flows which need an explicit tabId for captureFullPageWithOcr.
     * @returns {Promise<number>} Resolves with tabId.
     */
    function _resolveCurrentTabId() {
        return ExtensionBridge.getTabInfo().then(function(info) {
            return info.id;
        });
    }

    function _captureAndOcrPipelined(tabId) {
        var ocrPromises = [];
        var capturedCount = 0;
        var pageUrl = '';
        var pageTitle = '';
        console.log(P, '_captureAndOcrPipelined START tabId:', tabId, '(type:', typeof tabId + ')');

        var progressHandler = function(progress) {
            console.log(P, 'progressHandler invoked: progress.tabId:', progress && progress.tabId, '(type:', typeof (progress && progress.tabId) + ') expected tabId:', tabId, '(type:', typeof tabId + ') hasScreenshot:', !!(progress && progress.screenshot), 'step:', progress && progress.step, 'total:', progress && progress.total);
            if (progress && progress.screenshot && progress.tabId === tabId) {
                capturedCount++;
                pageUrl = progress.pageUrl || pageUrl;
                pageTitle = progress.pageTitle || pageTitle;
                var pageIndex = progress.pageIndex || (capturedCount - 1);
                console.log(P, 'screenshot accepted: capturedCount:', capturedCount, 'pageIndex:', pageIndex, 'dataUrl.length:', progress.screenshot.length);
                if (typeof showToast === 'function') {
                    showToast('Capturing page ' + capturedCount + ' of ' + (progress.total || '?') + '\u2026', 'info');
                }
                var ocrP = _ocrSingleScreenshot(progress.screenshot, pageUrl, pageTitle).then(function(text) {
                    console.log(P, 'OCR done for pageIndex:', pageIndex, 'text.length:', text ? text.length : 0);
                    return { index: pageIndex, text: text };
                });
                ocrPromises.push(ocrP);
            } else if (progress && progress.screenshot) {
                console.warn(P, 'screenshot FILTERED OUT — tabId mismatch: progress.tabId:', progress.tabId, 'expected:', tabId);
            }
        };

        ExtensionBridge.onProgress(progressHandler);
        console.log(P, 'progressHandler registered, calling captureFullPageWithOcr...');

        return ExtensionBridge.captureFullPageWithOcr(tabId, {})
            .then(function(meta) {
                console.log(P, 'captureFullPageWithOcr resolved. meta:', JSON.stringify(meta), 'ocrPromises.length:', ocrPromises.length);
                ExtensionBridge.offProgress(progressHandler);
                return Promise.all(ocrPromises).then(function(results) {
                    console.log(P, 'all OCR done. results.length:', results.length);
                    results.sort(function(a, b) { return a.index - b.index; });
                    var combinedText = results
                        .filter(function(r) { return r.text; })
                        .map(function(r) { return r.text; })
                        .join('\n\n--- PAGE ---\n\n');
                    var pages = results.map(function(r) { return { index: r.index, text: r.text }; });
                    console.log(P, 'combinedText.length:', combinedText.length, 'pages:', pages.length);
                    return {
                        url: meta.pageUrl || pageUrl,
                        title: meta.pageTitle || pageTitle,
                        content: combinedText,
                        isOcr: true,
                        ocrPagesData: pages,
                        tabId: tabId
                    };
                });
            })
            .catch(function(err) {
                ExtensionBridge.offProgress(progressHandler);
                console.error(P, '_captureAndOcrPipelined error:', err);
                throw err;
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

        // DOM extraction (default / main button click)
        $('#ext-extract-page, #ext-extract-dom').on('click', function(e) {
            e.preventDefault();
            var $btn = $('#ext-extract-page');
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

        // OCR extraction — single viewport screenshot + LLM OCR
        $('#ext-extract-ocr').on('click', function(e) {
            e.preventDefault();
            var $btn = $('#ext-extract-page');
            $btn.prop('disabled', true).find('i').removeClass('fa-globe').addClass('fa-spinner fa-spin');
            if (typeof showToast === 'function') showToast('Taking screenshot for OCR…', 'info');
            _resolveCurrentTabId().then(function(tabId) {
                return ExtensionBridge.captureScreenshot(tabId).then(function(result) {
                    return _ocrSingleScreenshot(result.dataUrl, '', '').then(function(text) {
                        return ExtensionBridge.getTabInfo().then(function(info) {
                            return { url: info.url, title: info.title, content: text, isOcr: true };
                        }).catch(function() {
                            return { url: '', title: '', content: text, isOcr: true };
                        });
                    });
                });
            }).then(function(data) {
                PageContextManager.setSingleContext(data);
                if (typeof showToast === 'function') showToast('OCR extraction complete', 'success');
            }).catch(function(err) {
                if (typeof showToast === 'function') showToast('OCR failed: ' + (err.message || err), 'danger');
            }).finally(function() {
                $btn.prop('disabled', false).find('i').removeClass('fa-spinner fa-spin').addClass('fa-globe');
            });
        });

        // Full Page OCR — scrolling capture + LLM OCR pipelined
        $('#ext-extract-full-ocr').on('click', function(e) {
            e.preventDefault();
            var $btn = $('#ext-extract-page');
            $btn.prop('disabled', true).find('i').removeClass('fa-globe').addClass('fa-spinner fa-spin');
            if (typeof showToast === 'function') showToast('Starting full-page OCR…', 'info');
            _resolveCurrentTabId().then(function(tabId) {
                return PageContextManager.capturePageWithOcr(tabId);
            }).catch(function(err) {
                if (typeof showToast === 'function') showToast('Full-page OCR failed: ' + (err.message || err), 'danger');
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
            }).catch(function(err) {
                console.error(P, 'capturePageWithOcr error:', err);
                if (typeof showToast === 'function') {
                    showToast('Full-page OCR failed: ' + (err.message || String(err)), 'danger');
                }
                throw err;
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
