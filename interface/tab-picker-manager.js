/**
 * TabPickerManager - Bootstrap 4.6 modal for multi-tab capture.
 * Fetches open tabs via ExtensionBridge.listTabs(), lets user select tabs
 * with per-tab capture mode, then captures and sends results to PageContextManager.
 */
var TabPickerManager = (function() {
    'use strict';

    var _tabs = [];
    var _capturing = false;
    var _cancelRequested = false;

    function _renderTabs(tabs) {
        _tabs = tabs || [];
        var $list = $('#tab-picker-list');
        $list.empty();

        if (_tabs.length === 0) {
            $list.html('<p class="text-muted p-3">No tabs found.</p>');
            return;
        }

        _tabs.forEach(function(tab, idx) {
            var favicon = tab.favIconUrl || '';
            var faviconHtml = favicon
                ? '<img src="' + $('<span>').text(favicon).html() + '" alt="" class="mr-2" style="width:16px;height:16px;">'
                : '<i class="fa fa-file-o mr-2" style="width:16px;"></i>';

            var html = '<div class="tab-picker-item d-flex align-items-center border-bottom" data-idx="' + idx + '">'
                + '<div class="custom-control custom-checkbox mr-2">'
                + '<input type="checkbox" class="custom-control-input tab-check" id="tab-check-' + idx + '" data-idx="' + idx + '">'
                + '<label class="custom-control-label" for="tab-check-' + idx + '"></label>'
                + '</div>'
                + faviconHtml
                + '<div class="flex-grow-1 text-truncate">'
                + '<div class="tab-title text-truncate">' + $('<span>').text(tab.title || 'Untitled').html() + '</div>'
                + '<small class="text-muted text-truncate d-block">' + $('<span>').text(tab.url || '').html() + '</small>'
                + '</div>'
                + '<select class="custom-select custom-select-sm ml-2 tab-mode-select" style="width:auto;" data-idx="' + idx + '">'
                + '<option value="auto">Auto</option>'
                + '<option value="dom">DOM</option>'
                + '<option value="ocr">OCR</option>'
                + '<option value="full_ocr">Full OCR</option>'
                + '</select>'
                + '</div>';
            $list.append(html);
        });
    }

    /**
     * Normalize UI mode names to wire protocol names.
     * UI uses underscores (full_ocr), operations-handler expects hyphens (full-ocr).
     * @param {string} uiMode - Mode from the dropdown (auto, dom, ocr, full_ocr).
     * @returns {string} Wire-protocol mode name.
     */
    function _normalizeMode(uiMode) {
        if (uiMode === 'full_ocr') return 'full-ocr';
        return uiMode || 'auto';
    }

    function _getSelectedTabs() {
        var selected = [];
        $('#tab-picker-list .tab-check:checked').each(function() {
            var idx = parseInt($(this).data('idx'));
            var mode = $('#tab-picker-list .tab-mode-select[data-idx="' + idx + '"]').val();
            if (_tabs[idx]) {
                selected.push({
                    tabId: _tabs[idx].id,
                    url: _tabs[idx].url,
                    title: _tabs[idx].title,
                    mode: _normalizeMode(mode)
                });
            }
        });
        return selected;
    }

    function _updateSelectionCount() {
        var count = $('#tab-picker-list .tab-check:checked').length;
        $('#tab-picker-selected-count').text(count + ' selected');
        $('#tab-picker-capture-btn').prop('disabled', count === 0 || _capturing);
    }

    function _setProgress(percent, text) {
        var $bar = $('#tab-picker-progress-bar');
        $bar.css('width', percent + '%').attr('aria-valuenow', percent);
        if (text) $('#tab-picker-progress-text').text(text);
        if (percent > 0) {
            $('#tab-picker-progress').show();
        }
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

    function _startCapture() {
        var selected = _getSelectedTabs();
        if (selected.length === 0) return;

        _capturing = true;
        _cancelRequested = false;
        $('#tab-picker-capture-btn').prop('disabled', true).text('Capturing…');
        $('#tab-picker-cancel-btn').show();
        _setProgress(0, 'Checking cache…');

        // Build batch lookup entries for extraction cache (modes already normalized)
        var entries = selected.map(function(t) {
            return { url: t.url, mode: t.mode };
        });

        // Attempt cache lookup; if it fails (extension unavailable, timeout), treat all as uncached
        ExtensionBridge.cacheBatchLookup(entries).catch(function() {
            return { results: [] };
        }).then(function(cacheResponse) {
            var cacheResults = (cacheResponse && cacheResponse.results) || [];
            var cacheMap = {};
            cacheResults.forEach(function(r) {
                if (r.hit && r.data) {
                    cacheMap[r.url + '::' + r.mode] = r.data;
                }
            });

            // Partition selected tabs into cached and uncached
            var cachedTabs = [];
            var uncachedTabs = [];
            selected.forEach(function(t) {
                var key = t.url + '::' + t.mode;
                if (cacheMap[key]) {
                    cachedTabs.push(t);
                } else {
                    uncachedTabs.push(t);
                }
            });

            // Build result objects from cache data for cached tabs
            var cachedResults = cachedTabs.map(function(tab) {
                var data = cacheMap[tab.url + '::' + tab.mode];
                var result = {
                    tabId: tab.tabId,
                    url: data.url || tab.url,
                    title: data.title || tab.title,
                    content: data.content || '',
                    mode: tab.mode
                };
                if (data.isOcr) {
                    result.isOcr = true;
                }
                return result;
            });

            // Show progress for cached tabs
            if (cachedTabs.length > 0) {
                _setProgress(
                    Math.round((cachedTabs.length / selected.length) * 50),
                    cachedTabs.length + ' tab(s) served from cache (cached)'
                );
                if (typeof showToast === 'function') {
                    showToast(cachedTabs.length + ' tab(s) served from cache', 'info');
                }
            }

            // If all tabs cached, skip captureMultiTab entirely
            if (uncachedTabs.length === 0) {
                _setProgress(100, 'All tabs from cache');
                _finishCapture(cachedResults);
                return;
            }

            // Proceed with uncached tabs only
            _setProgress(
                Math.round((cachedTabs.length / selected.length) * 50),
                'Capturing ' + uncachedTabs.length + ' uncached tab(s)…'
            );

            var tabDescriptors = uncachedTabs.map(function(t) {
                return { tabId: t.tabId, mode: t.mode };
            });

            // Per-tab OCR promise tracking only for uncached tabs
            var ocrPromisesByTab = {};
            uncachedTabs.forEach(function(t) { ocrPromisesByTab[t.tabId] = []; });

            // Lookup includes all selected tabs for progress display safety
            var tabLookup = {};
            selected.forEach(function(t) { tabLookup[t.tabId] = t; });

            var progressHandler = function(progress) {
                if (!progress) return;

                if (progress.type === 'tab-progress') {
                    var pct = Math.round(((progress.step - 1) / progress.total) * 100);
                    var tabInfo = tabLookup[progress.tabId];
                    var tabTitle = tabInfo ? tabInfo.title : ('Tab ' + progress.step);
                    _setProgress(pct, 'Capturing: ' + tabTitle + ' (' + progress.mode + ')');
                } else if (progress.type === 'screenshot' && progress.screenshot) {
                    var ocrP = _ocrSingleScreenshot(
                        progress.screenshot,
                        progress.pageUrl || '',
                        progress.pageTitle || ''
                    ).then(function(text) {
                        return { index: progress.pageIndex || 0, text: text };
                    });
                    if (ocrPromisesByTab[progress.tabId]) {
                        ocrPromisesByTab[progress.tabId].push(ocrP);
                    }
                    if (typeof showToast === 'function') {
                        showToast('OCR pipelining: tab ' + progress.tabId + ' screenshot ' + (progress.step || '?'), 'info');
                    }
                } else if (progress.type === 'capture-progress') {
                    var tabInfo2 = tabLookup[progress.tabId];
                    var tabTitle2 = tabInfo2 ? tabInfo2.title : 'Tab';
                    _setProgress(
                        Math.round(((progress.step || 0) / (progress.total || 1)) * 100),
                        tabTitle2 + ': ' + (progress.message || '')
                    );
                }
            };

            ExtensionBridge.onProgress(progressHandler);

            ExtensionBridge.captureMultiTab(tabDescriptors).then(function(response) {
                var captureResults = response.results || [];
                _setProgress(90, 'Awaiting OCR results…');
                _assembleResults(uncachedTabs, captureResults, ocrPromisesByTab, progressHandler, cachedResults);
            }).catch(function(err) {
                ExtensionBridge.offProgress(progressHandler);
                if (cachedResults.length > 0) {
                    if (typeof showToast === 'function') {
                        showToast('Some tabs failed, using ' + cachedResults.length + ' cached result(s)', 'warning');
                    }
                    _finishCapture(cachedResults);
                } else {
                    _capturing = false;
                    $('#tab-picker-capture-btn').prop('disabled', false).text('Capture Selected');
                    $('#tab-picker-cancel-btn').hide();
                    _setProgress(0, '');
                    if (typeof showToast === 'function') {
                        showToast('Multi-tab capture failed: ' + (err.message || err), 'danger');
                    }
                }
            });
        });
    }

    function _assembleResults(selected, captureResults, ocrPromisesByTab, progressHandler, cachedResults) {
        var allOcrPromises = [];
        var ocrTabIds = [];

        selected.forEach(function(tab) {
            var promises = ocrPromisesByTab[tab.tabId] || [];
            if (promises.length > 0) {
                allOcrPromises.push(
                    Promise.all(promises).then(function(ocrResults) {
                        ocrResults.sort(function(a, b) { return a.index - b.index; });
                        var text = ocrResults
                            .filter(function(r) { return r.text; })
                            .map(function(r) { return r.text; })
                            .join('\n\n--- PAGE ---\n\n');
                        var pages = ocrResults.map(function(r) { return { index: r.index, text: r.text }; });
                        return { tabId: tab.tabId, text: text, pages: pages };
                    })
                );
                ocrTabIds.push(tab.tabId);
            }
        });

        Promise.all(allOcrPromises).then(function(ocrByTab) {
            var ocrMap = {};
            ocrByTab.forEach(function(r) { ocrMap[r.tabId] = r; });

            var results = [];
            for (var i = 0; i < selected.length; i++) {
                var tab = selected[i];
                var captureResult = captureResults[i] || {};
                var ocrData = ocrMap[tab.tabId];

                if (ocrData && ocrData.text) {
                    results.push({
                        tabId: tab.tabId,
                        url: captureResult.url || tab.url,
                        title: captureResult.title || tab.title,
                        content: ocrData.text,
                        isOcr: true,
                        ocrPagesData: ocrData.pages
                    });
                    // Fire-and-forget: store OCR text in extraction cache
                    ExtensionBridge.cacheStore(tab.url, tab.mode, {
                        content: ocrData.text,
                        title: captureResult.title || tab.title,
                        tabId: tab.tabId,
                        url: captureResult.url || tab.url,
                        wordCount: ocrData.text.split(/\s+/).length,
                        charCount: ocrData.text.length,
                        isOcr: true
                    }).catch(function() {});
                } else {
                    results.push({
                        tabId: tab.tabId,
                        url: captureResult.url || tab.url,
                        title: captureResult.title || tab.title,
                        content: captureResult.content || captureResult.text || ''
                    });
                }
            }

            var mergedResults = (cachedResults || []).concat(results);

            ExtensionBridge.offProgress(progressHandler);
            _finishCapture(mergedResults);
        }).catch(function() {
            ExtensionBridge.offProgress(progressHandler);
            _finishCapture(cachedResults || []);
        });
    }

    function _finishCapture(results) {
        _capturing = false;
        $('#tab-picker-capture-btn').prop('disabled', false).text('Capture Selected');
        $('#tab-picker-cancel-btn').hide();
        _setProgress(100, _cancelRequested ? 'Cancelled' : 'Done!');

        if (results.length > 0 && !_cancelRequested) {
            if (typeof PageContextManager !== 'undefined') {
                PageContextManager.setMultiTabContext(results);
            }
            var ocrCount = results.filter(function(r) { return r.isOcr; }).length;
            var domCount = results.length - ocrCount;
            var msg = results.length + ' tab(s) captured';
            if (ocrCount > 0) msg += ' (' + ocrCount + ' OCR, ' + domCount + ' DOM)';
            if (typeof showToast === 'function') {
                showToast(msg, 'success');
            }
            setTimeout(function() { $('#tab-picker-modal').modal('hide'); }, 500);
        }
    }

    function _bindEvents() {
        $('#tab-picker-select-all').on('click', function() {
            $('#tab-picker-list .tab-check').prop('checked', true);
            _updateSelectionCount();
        });

        $('#tab-picker-deselect-all').on('click', function() {
            $('#tab-picker-list .tab-check').prop('checked', false);
            _updateSelectionCount();
        });

        $(document).on('change', '#tab-picker-list .tab-check', function() {
            _updateSelectionCount();
        });

        $('#tab-picker-capture-btn').on('click', function() {
            _startCapture();
        });

        $('#tab-picker-cancel-btn').on('click', function() {
            _cancelRequested = true;
        });

        $('#tab-picker-modal').on('hidden.bs.modal', function() {
            _cancelRequested = true;
            _setProgress(0, '');
            $('#tab-picker-progress').hide();
        });
    }

    return {
        init: function() {
            _bindEvents();
        },

        show: function() {
            if (!ExtensionBridge.isAvailable) {
                if (typeof showToast === 'function') showToast('Extension not available', 'warning');
                return;
            }

            var $list = $('#tab-picker-list');
            $list.html('<p class="text-muted p-3"><i class="fa fa-spinner fa-spin"></i> Loading tabs…</p>');
            $('#tab-picker-progress').hide();
            $('#tab-picker-cancel-btn').hide();
            $('#tab-picker-selected-count').text('0 selected');
            $('#tab-picker-capture-btn').prop('disabled', true).text('Capture Selected');
            $('#tab-picker-modal').modal('show');

            ExtensionBridge.listTabs().then(function(data) {
                var tabs = data.tabs || data || [];
                _renderTabs(tabs);
                _updateSelectionCount();
            }).catch(function(err) {
                $list.html('<p class="text-danger p-3">Failed to load tabs: ' + (err.message || err) + '</p>');
            });
        }
    };
})();

$(document).ready(function() {
    TabPickerManager.init();
});
