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
 *   - sendMessage(tabId, message): Promise<any> — sends message to content script
 *   - getTab(tabId): Promise<object> — gets tab info
 * @param {object} [options] - Capture options
 * @param {number} [options.overlapRatio=0.1] - Overlap ratio between screenshots (0-1)
 * @param {number} [options.delayMs=1000] - Delay after scroll before capture (milliseconds)
 * @param {function} [onProgress] - Progress callback(step, total, message)
 * @returns {Promise<{screenshots: string[], url: string, title: string, meta: object}>}
 * @throws {Error} If capture fails or tab is restricted
 */
export async function captureFullPage(tabId, chromeApi, options = {}, onProgress = null) {
    const overlapRatio = Number.isFinite(options?.overlapRatio) ? options.overlapRatio : 0.1;
    const delayMs = Number.isFinite(options?.delayMs) ? options.delayMs : 1000;

    // Get tab info
    const tab = await chromeApi.getTab(tabId);
    if (!tab?.id) {
        throw new Error('No tab available for capture');
    }

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

    try {
        const ctxResult = await chromeApi.sendMessage(tab.id, {
            type: MESSAGE_TYPES.INIT_CAPTURE_CONTEXT,
            options: {}
        });

        if (ctxResult && ctxResult.ok) {
            useContextProtocol = true;
            contextId = ctxResult.contextId;
            scrollHeight = ctxResult.metrics.scrollHeight;
            clientHeight = ctxResult.metrics.clientHeight;
            maxScrollTop = ctxResult.metrics.maxScrollTop;
            originalScrollTop = ctxResult.metrics.scrollTop;
            targetKind = ctxResult.target.kind;
            targetDescription = ctxResult.target.description;
            console.log(`[Full-Page Capture] Capture context: ${targetKind} (${targetDescription}), ` +
                `scrollHeight=${scrollHeight}, clientHeight=${clientHeight}`);
        } else if (ctxResult && !ctxResult.ok) {
            console.log(`[Full-Page Capture] Capture context failed: ${ctxResult.reason}. ` +
                `Falling back to legacy scroll.`);
        }
    } catch (ctxErr) {
        console.log('[Full-Page Capture] INIT_CAPTURE_CONTEXT not supported, using legacy:', ctxErr.message);
    }

    // Fallback to legacy protocol
    if (!useContextProtocol) {
        const metrics = await chromeApi.sendMessage(tab.id, { type: MESSAGE_TYPES.GET_PAGE_METRICS });
        clientHeight = Math.max(1, metrics.viewportHeight || 1);
        scrollHeight = Math.max(clientHeight, metrics.scrollHeight || clientHeight);
        maxScrollTop = Math.max(0, scrollHeight - clientHeight);
        originalScrollTop = metrics.scrollY || 0;
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

    // Scroll to top before capture
    if (originalScrollTop > 0) {
        if (useContextProtocol) {
            await chromeApi.sendMessage(tab.id, {
                type: MESSAGE_TYPES.SCROLL_CONTEXT_TO,
                contextId,
                top: 0
            });
        } else {
            await chromeApi.sendMessage(tab.id, { type: MESSAGE_TYPES.SCROLL_TO, y: 0 });
        }
        await new Promise(resolve => setTimeout(resolve, delayMs));
    }

    // Capture screenshots at each position
    const screenshots = [];
    for (let i = 0; i < positions.length; i += 1) {
        const y = positions[i];

        if (onProgress) {
            onProgress(i + 1, positions.length, `Capturing screenshot ${i + 1} of ${positions.length}`);
        }

        // Scroll to position
        if (useContextProtocol) {
            await chromeApi.sendMessage(tab.id, {
                type: MESSAGE_TYPES.SCROLL_CONTEXT_TO,
                contextId,
                top: y
            });
        } else {
            await chromeApi.sendMessage(tab.id, { type: MESSAGE_TYPES.SCROLL_TO, y });
        }
        await new Promise(resolve => setTimeout(resolve, delayMs));

        // Re-check metrics mid-capture for virtualized content (every 5 frames)
        if (useContextProtocol && i > 0 && i % 5 === 0) {
            try {
                const refreshed = await chromeApi.sendMessage(tab.id, {
                    type: MESSAGE_TYPES.GET_CONTEXT_METRICS,
                    contextId
                });
                if (refreshed?.ok && refreshed.metrics.maxScrollTop > maxScrollTop) {
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
                    }
                }
            } catch (_) { /* non-critical */ }
        }

        // Capture screenshot with retry on rate limit
        try {
            const dataUrl = await chromeApi.captureVisibleTab(tab.windowId);
            screenshots.push(dataUrl);
        } catch (e) {
            const msg = e?.message || String(e);
            if (msg.includes('MAX_CAPTURE_VISIBLE_TAB_CALLS_PER_SECOND')) {
                await new Promise(resolve => setTimeout(resolve, 1200));
                const retryUrl = await chromeApi.captureVisibleTab(tab.windowId);
                screenshots.push(retryUrl);
            } else {
                throw e;
            }
        }
    }

    // Restore original scroll position
    if (useContextProtocol) {
        await chromeApi.sendMessage(tab.id, {
            type: MESSAGE_TYPES.SCROLL_CONTEXT_TO,
            contextId,
            top: originalScrollTop
        });
        await chromeApi.sendMessage(tab.id, {
            type: MESSAGE_TYPES.RELEASE_CAPTURE_CONTEXT,
            contextId
        });
    } else {
        await chromeApi.sendMessage(tab.id, { type: MESSAGE_TYPES.SCROLL_TO, y: originalScrollTop });
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
            targetDescription
        }
    };
}
