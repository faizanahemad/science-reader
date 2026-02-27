/**
 * Full-page capture orchestration module.
 * 
 * Scrolls a page capturing screenshots at each scroll position.
 * Used by both the current extension and headless bridge extension.
 * Chrome API calls are parameterized via the chromeApi adapter to
 * allow different extensions to provide their own implementations.
 *
 * @module full-page-capture
 */

// Message types for content script communication
const MESSAGE_TYPES = {
    INIT_CAPTURE_CONTEXT: 'INIT_CAPTURE_CONTEXT',
    SCROLL_CONTEXT_TO: 'SCROLL_CONTEXT_TO',
    GET_CONTEXT_METRICS: 'GET_CONTEXT_METRICS',
    RELEASE_CAPTURE_CONTEXT: 'RELEASE_CAPTURE_CONTEXT',
    GET_PAGE_METRICS: 'GET_PAGE_METRICS',
    SCROLL_TO: 'SCROLL_TO'
};

var FPC = '[Full-Page Capture]';

/**
 * Capture full-page screenshots by scrolling and capturing at each position.
 * 
 * Detects the scroll container (window or inner element), scrolls it step-by-step
 * with overlap, and grabs visible frames. Supports both modern capture context
 * protocol (for inner scroll containers) and legacy window scrolling.
 * 
 * @param {number} tabId - Chrome tab ID to capture
 * @param {object} chromeApi - Adapter object providing Chrome API functions:
 *   - captureVisibleTab(windowId): Promise<string> — captures visible tab as data URL
 *   - sendMessage(tabId, message, opts?): Promise<any> — sends message to content script; opts: {frameId?}
 *   - getTab(tabId): Promise<object> — gets tab info
 * @param {object} [options] - Capture options
 * @param {number} [options.overlapRatio=0.1] - Overlap ratio between screenshots (0-1)
 * @param {number} [options.delayMs=1000] - Delay after scroll before capture (milliseconds)
 * @param {number} [options.captureFrameId] - Frame ID to send scroll messages to (for sub-frame scroll)
 * @param {string} [options.captureContextId] - Pre-existing contextId (skip INIT_CAPTURE_CONTEXT)
 * @param {object} [options.captureContextMetrics] - Pre-existing metrics (used with captureContextId)
 * @param {object} [options.captureContextTarget] - Pre-existing target info (used with captureContextId)
 * @param {function} [onProgress] - Progress callback(step, total, message)
 * @returns {Promise<{screenshots: string[], url: string, title: string, meta: object}>}
 * @throws {Error} If capture fails or tab is restricted
 */
export async function captureFullPage(tabId, chromeApi, options = {}, onProgress = null) {
    const overlapRatio = Number.isFinite(options?.overlapRatio) ? options.overlapRatio : 0.1;
    const delayMs = Number.isFinite(options?.delayMs) ? options.delayMs : 1000;
    const captureFrameId = (options?.captureFrameId !== undefined) ? options.captureFrameId : undefined;
    const msgOpts = captureFrameId !== undefined ? { frameId: captureFrameId } : {};

    console.log(FPC, 'captureFullPage START tabId:', tabId, 'captureFrameId:', captureFrameId,
        'delayMs:', delayMs, 'overlapRatio:', overlapRatio);

    // Get tab info
    const tab = await chromeApi.getTab(tabId);
    if (!tab?.id) {
        throw new Error('No tab available for capture');
    }
    console.log(FPC, 'tab:', tab.title, 'url:', tab.url, 'windowId:', tab.windowId);

    // Check for restricted URLs
    if (tab.url?.startsWith('chrome://') || tab.url?.startsWith('chrome-extension://') ||
        tab.url?.startsWith('about:') || tab.url?.startsWith('edge://')) {
        throw new Error('Cannot capture screenshots on restricted URLs');
    }

    // Try new capture context protocol (supports inner scroll containers)
    let useContextProtocol = false;
    let contextId = null;
    let scrollHeight, clientHeight, maxScrollTop, originalScrollTop;
    let targetKind = 'window';
    let targetDescription = 'legacy';

    // Use pre-supplied context if caller already ran INIT_CAPTURE_CONTEXT (e.g. sub-frame probe)
    if (options?.captureContextId && options?.captureContextMetrics) {
        useContextProtocol = true;
        contextId = options.captureContextId;
        scrollHeight = options.captureContextMetrics.scrollHeight;
        clientHeight = options.captureContextMetrics.clientHeight;
        maxScrollTop = options.captureContextMetrics.maxScrollTop;
        originalScrollTop = options.captureContextMetrics.scrollTop;
        targetKind = options.captureContextTarget?.kind || 'element';
        targetDescription = options.captureContextTarget?.description || 'pre-supplied';
        console.log(FPC, 'using pre-supplied context:', contextId, 'frameId:', captureFrameId,
            'kind:', targetKind, 'scrollH:', scrollHeight, 'clientH:', clientHeight, 'maxScroll:', maxScrollTop);
    } else {
        // Try INIT_CAPTURE_CONTEXT (to top frame or specified sub-frame)
        try {
            console.log(FPC, 'sending INIT_CAPTURE_CONTEXT frameId:', captureFrameId);
            const ctxResult = await chromeApi.sendMessage(tab.id, {
                type: MESSAGE_TYPES.INIT_CAPTURE_CONTEXT,
                options: {}
            }, msgOpts);

            console.log(FPC, 'INIT_CAPTURE_CONTEXT response ok:', ctxResult && ctxResult.ok,
                'reason:', ctxResult && ctxResult.reason, 'kind:', ctxResult && ctxResult.target && ctxResult.target.kind);

            if (ctxResult && ctxResult.ok) {
                useContextProtocol = true;
                contextId = ctxResult.contextId;
                scrollHeight = ctxResult.metrics.scrollHeight;
                clientHeight = ctxResult.metrics.clientHeight;
                maxScrollTop = ctxResult.metrics.maxScrollTop;
                originalScrollTop = ctxResult.metrics.scrollTop;
                targetKind = ctxResult.target.kind;
                targetDescription = ctxResult.target.description;
                console.log(FPC, `Capture context: ${targetKind} (${targetDescription}), ` +
                    `scrollHeight=${scrollHeight}, clientHeight=${clientHeight}, maxScrollTop=${maxScrollTop}`);
            } else if (ctxResult && !ctxResult.ok) {
                console.log(FPC, `Capture context failed: ${ctxResult.reason} (${ctxResult.debug}). Falling back to legacy scroll.`);
            }
        } catch (ctxErr) {
            console.log(FPC, 'INIT_CAPTURE_CONTEXT threw, using legacy:', ctxErr.message);
        }
    }

    // Fallback to legacy protocol
    if (!useContextProtocol) {
        console.log(FPC, 'using legacy GET_PAGE_METRICS');
        const metrics = await chromeApi.sendMessage(tab.id, { type: MESSAGE_TYPES.GET_PAGE_METRICS }, msgOpts);
        console.log(FPC, 'GET_PAGE_METRICS:', JSON.stringify(metrics));
        clientHeight = Math.max(1, metrics.viewportHeight || 1);
        scrollHeight = Math.max(clientHeight, metrics.scrollHeight || clientHeight);
        maxScrollTop = Math.max(0, scrollHeight - clientHeight);
        originalScrollTop = metrics.scrollY || 0;
        console.log(FPC, 'legacy: clientH:', clientHeight, 'scrollH:', scrollHeight, 'maxScroll:', maxScrollTop);
    }

    // Calculate scroll positions with overlap
    const overlapPx = Math.max(0, Math.round(clientHeight * overlapRatio));
    const step = Math.max(100, clientHeight - overlapPx);

    const positions = [];
    for (let y = 0; y <= maxScrollTop; y += step) {
        positions.push(y);
    }
    if (positions.length === 0 || positions[positions.length - 1] !== maxScrollTop) {
        positions.push(maxScrollTop);
    }
    console.log(FPC, 'scroll plan: positions:', positions.length, 'step:', step, 'overlapPx:', overlapPx,
        'first 5:', JSON.stringify(positions.slice(0, 5)), positions.length > 5 ? '...' : '');

    // Scroll to top before capture
    if (originalScrollTop > 0) {
        console.log(FPC, 'scrolling to top (was at', originalScrollTop + ')');
        if (useContextProtocol) {
            await chromeApi.sendMessage(tab.id, {
                type: MESSAGE_TYPES.SCROLL_CONTEXT_TO,
                contextId,
                top: 0
            }, msgOpts);
        } else {
            await chromeApi.sendMessage(tab.id, { type: MESSAGE_TYPES.SCROLL_TO, y: 0 }, msgOpts);
        }
        await new Promise(resolve => setTimeout(resolve, delayMs));
    }

    // Capture screenshots at each position
    const screenshots = [];
    for (let i = 0; i < positions.length; i += 1) {
        const y = positions[i];
        console.log(FPC, `screenshot ${i + 1}/${positions.length} scrollY=${y} contextId=${contextId} frameId=${captureFrameId}`);

        if (onProgress) {
            onProgress(i + 1, positions.length, `Capturing screenshot ${i + 1} of ${positions.length}`);
        }

        // Scroll to position
        if (useContextProtocol) {
            try {
                const scrollResp = await chromeApi.sendMessage(tab.id, {
                    type: MESSAGE_TYPES.SCROLL_CONTEXT_TO,
                    contextId,
                    top: y
                }, msgOpts);
                console.log(FPC, `  SCROLL_CONTEXT_TO resp ok:${scrollResp && scrollResp.ok} settled:${scrollResp && scrollResp.scrollTop}`);
                if (scrollResp && scrollResp.ok === false) {
                    console.warn(FPC, '  scroll not ok:', JSON.stringify(scrollResp));
                }
            } catch (scrollErr) {
                console.warn(FPC, '  SCROLL_CONTEXT_TO threw:', scrollErr.message);
            }
        } else {
            try {
                await chromeApi.sendMessage(tab.id, { type: MESSAGE_TYPES.SCROLL_TO, y }, msgOpts);
            } catch (scrollErr) {
                console.warn(FPC, '  SCROLL_TO threw:', scrollErr.message);
            }
        }
        await new Promise(resolve => setTimeout(resolve, delayMs));

        // Re-check metrics mid-capture for virtualized content (every 5 frames)
        if (useContextProtocol && i > 0 && i % 5 === 0) {
            try {
                const refreshed = await chromeApi.sendMessage(tab.id, {
                    type: MESSAGE_TYPES.GET_CONTEXT_METRICS,
                    contextId
                }, msgOpts);
                if (refreshed?.ok && refreshed.metrics.maxScrollTop > maxScrollTop) {
                    console.log(FPC, '  content grew: maxScrollTop', maxScrollTop, '->', refreshed.metrics.maxScrollTop);
                    maxScrollTop = refreshed.metrics.maxScrollTop;
                    scrollHeight = refreshed.metrics.scrollHeight;
                    // Extend positions if content grew
                    const lastPos = positions[positions.length - 1];
                    if (lastPos < maxScrollTop) {
                        for (let ny = lastPos + step; ny <= maxScrollTop; ny += step) {
                            positions.push(ny);
                        }
                        if (positions[positions.length - 1] !== maxScrollTop) {
                            positions.push(maxScrollTop);
                        }
                        console.log(FPC, '  extended positions to', positions.length);
                    }
                }
            } catch (_) { /* non-critical */ }
        }

        // Capture screenshot with retry on rate limit
        try {
            const dataUrl = await chromeApi.captureVisibleTab(tab.windowId);
            console.log(FPC, `  captureVisibleTab OK dataUrl.length=${dataUrl ? dataUrl.length : 0}`);
            screenshots.push(dataUrl);
        } catch (e) {
            const msg = e?.message || String(e);
            console.warn(FPC, `  captureVisibleTab FAILED i=${i}:`, msg);
            if (msg.includes('MAX_CAPTURE_VISIBLE_TAB_CALLS_PER_SECOND')) {
                console.log(FPC, '  rate limited, waiting 1200ms');
                await new Promise(resolve => setTimeout(resolve, 1200));
                try {
                    const retryUrl = await chromeApi.captureVisibleTab(tab.windowId);
                    screenshots.push(retryUrl);
                    console.log(FPC, '  retry OK');
                } catch (retryErr) {
                    console.warn(FPC, '  retry also failed:', retryErr.message);
                }
            } else {
                throw e;
            }
        }
    }

    console.log(FPC, 'capture loop done. screenshots:', screenshots.length, 'of', positions.length, 'positions');

    // Restore original scroll position
    if (useContextProtocol) {
        try {
            await chromeApi.sendMessage(tab.id, {
                type: MESSAGE_TYPES.SCROLL_CONTEXT_TO,
                contextId,
                top: originalScrollTop
            }, msgOpts);
            await chromeApi.sendMessage(tab.id, {
                type: MESSAGE_TYPES.RELEASE_CAPTURE_CONTEXT,
                contextId
            }, msgOpts);
        } catch (_) {}
    } else {
        try {
            await chromeApi.sendMessage(tab.id, { type: MESSAGE_TYPES.SCROLL_TO, y: originalScrollTop }, msgOpts);
        } catch (_) {}
    }

    return {
        screenshots,
        url: tab.url,
        title: tab.title,
        meta: {
            scrollHeight,
            clientHeight,
            viewportHeight: clientHeight,
            step,
            overlapPx,
            total: screenshots.length,
            targetKind,
            targetDescription,
            captureFrameId
        }
    };
}
