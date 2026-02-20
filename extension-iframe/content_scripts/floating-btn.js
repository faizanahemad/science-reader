/**
 * floating-btn.js — Iframe Sidepanel Extension content script.
 *
 * Purpose:
 *   Injects a floating action button (FAB) on every web page so the user can
 *   open the AI Assistant iframe sidepanel without clicking the toolbar icon.
 *
 * Positioning:
 *   Stacks above the original extension's FAB to avoid overlap.
 *   Original:  bottom 160px, right 12px  (blue, 40×40px)
 *   This FAB:  bottom 212px, right 12px  (purple, 40×40px)
 *             = 160px + 40px (btn height) + 12px (gap)
 *
 * Click behaviour:
 *   Sends OPEN_SIDEPANEL to background.js which calls chrome.sidePanel.open().
 *
 * Guard:
 *   Bails out if the button already exists (handles re-injection edge cases).
 */

(function () {
    'use strict';

    var BUTTON_ID = 'ai-assistant-iframe-floating-btn';
    var STYLE_ID  = 'ai-assistant-iframe-fab-styles';

    /**
     * Inject CSS for the FAB into <head>.
     * Uses a unique CSS variable namespace to avoid colliding with the original
     * extension's --ai-assistant-fab-* variables.
     */
    function injectStyles() {
        if (document.getElementById(STYLE_ID)) return;

        var style = document.createElement('style');
        style.id = STYLE_ID;
        style.textContent = [
            ':root {',
            '    --ai-iframe-fab-right:  12px;',
            '    --ai-iframe-fab-bottom: 212px;', /* 160 + 40 + 12 */
            '    --ai-iframe-fab-size:   40px;',
            '}',

            '#' + BUTTON_ID + ' {',
            '    position:      fixed;',
            '    bottom:        var(--ai-iframe-fab-bottom);',
            '    right:         var(--ai-iframe-fab-right);',
            '    width:         var(--ai-iframe-fab-size);',
            '    height:        var(--ai-iframe-fab-size);',
            '    border-radius: 50%;',
            '    background:    linear-gradient(135deg, #a855f7 0%, #7c3aed 100%);',
            '    border:        none;',
            '    color:         white;',
            '    font-size:     22px;',
            '    cursor:        pointer;',
            '    box-shadow:    0 4px 16px rgba(168, 85, 247, 0.45);',
            '    z-index:       2147483644;',
            '    transition:    transform 0.2s, box-shadow 0.2s;',
            '    display:       flex;',
            '    align-items:   center;',
            '    justify-content: center;',
            '}',

            '#' + BUTTON_ID + ':hover {',
            '    transform:  scale(1.08);',
            '    box-shadow: 0 6px 24px rgba(168, 85, 247, 0.65);',
            '}',

            '#' + BUTTON_ID + ':active {',
            '    transform: scale(0.95);',
            '}',

            '#' + BUTTON_ID + ' svg {',
            '    width:  20px;',
            '    height: 20px;',
            '    pointer-events: none;',
            '}',
        ].join('\n');

        document.head.appendChild(style);
    }

    /**
     * Build the SVG icon for the FAB.
     * Uses a simple chat-bubble-with-frame icon to visually distinguish it
     * from the original extension's chat icon.
     *
     * @returns {SVGElement}
     */
    function buildIcon() {
        var svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        svg.setAttribute('viewBox', '0 0 24 24');
        svg.setAttribute('fill', 'none');
        svg.setAttribute('stroke', 'currentColor');
        svg.setAttribute('stroke-width', '2');
        svg.setAttribute('stroke-linecap', 'round');
        svg.setAttribute('stroke-linejoin', 'round');

        /* Outer frame (represents the iframe/panel) */
        var rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
        rect.setAttribute('x', '3');
        rect.setAttribute('y', '3');
        rect.setAttribute('width', '18');
        rect.setAttribute('height', '18');
        rect.setAttribute('rx', '3');

        /* Vertical divider (represents the sidepanel split) */
        var line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
        line.setAttribute('x1', '15');
        line.setAttribute('y1', '3');
        line.setAttribute('x2', '15');
        line.setAttribute('y2', '21');

        svg.appendChild(rect);
        svg.appendChild(line);
        return svg;
    }

    /**
     * Create and inject the FAB into document.body.
     * Sends OPEN_SIDEPANEL to the background service worker on click.
     */
    function createFloatingButton() {
        if (document.getElementById(BUTTON_ID)) return;

        injectStyles();

        var button = document.createElement('button');
        button.id = BUTTON_ID;
        button.title = 'Open AI Assistant (iframe sidepanel)';
        button.setAttribute('aria-label', 'Open AI Assistant sidepanel');
        button.appendChild(buildIcon());

        button.addEventListener('click', function (e) {
            e.stopPropagation();
            e.preventDefault();

            chrome.runtime.sendMessage({ type: 'OPEN_SIDEPANEL' }, function (response) {
                if (chrome.runtime.lastError) {
                    /* Extension context invalidated — silently ignore */
                }
            });
        });

        document.body.appendChild(button);
    }

    /* Inject immediately if DOM is ready, otherwise wait. */
    if (document.body) {
        createFloatingButton();
    } else {
        document.addEventListener('DOMContentLoaded', createFloatingButton);
    }
})();
