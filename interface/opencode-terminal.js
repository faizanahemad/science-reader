/**
 * Terminal — xterm.js WebSocket bridge.
 *
 * Provides terminal UI in both a modal (inside interface.html) and
 * standalone page (terminal.html). Connects to /ws/terminal WebSocket.
 *
 * Dependencies (loaded via CDN script tags):
 *   - @xterm/xterm@5.5.0
 *   - @xterm/addon-fit@0.10.0
 *   - @xterm/addon-web-links@0.11.0
 *
 * Public API:
 *   OpencodeTerminal.init(containerId)  — create Terminal instance
 *   OpencodeTerminal.connect()          — open WebSocket connection
 *   OpencodeTerminal.disconnect()       — close WebSocket cleanly
 *   OpencodeTerminal.dispose()          — full cleanup (disconnect + dispose terminal)
 *   OpencodeTerminal.fit()              — re-fit terminal to container
 *   OpencodeTerminal.focus()            — focus terminal input
 *
 * WebSocket protocol (JSON):
 *   Outbound: { type: "input"|"resize"|"ping", ... }
 *   Inbound:  { type: "output"|"exit"|"error"|"pong", ... }
 */
var OpencodeTerminal = (function() {
    var term = null;
    var socket = null;
    var fitAddon = null;
    var webLinksAddon = null;
    var connected = false;
    var reconnectAttempts = 0;
    var MAX_RECONNECT = 3;
    var containerEl = null;
    var pingInterval = null;

    // Catppuccin Mocha color theme
    var THEME = {
        background: '#1e1e2e',
        foreground: '#cdd6f4',
        cursor: '#f5e0dc',
        cursorAccent: '#1e1e2e',
        selectionBackground: '#585b70',
        black: '#45475a',
        red: '#f38ba8',
        green: '#a6e3a1',
        yellow: '#f9e2af',
        blue: '#89b4fa',
        magenta: '#f5c2e7',
        cyan: '#94e2d5',
        white: '#bac2de',
        brightBlack: '#585b70',
        brightRed: '#f38ba8',
        brightGreen: '#a6e3a1',
        brightYellow: '#f9e2af',
        brightBlue: '#89b4fa',
        brightMagenta: '#f5c2e7',
        brightCyan: '#94e2d5',
        brightWhite: '#a6adc8'
    };

    /**
     * Initialize the terminal instance and load addons.
     * Must be called before connect(). The container element must exist in the DOM.
     *
     * @param {string} containerId - DOM element ID for the terminal container.
     */
    function init(containerId) {
        containerEl = document.getElementById(containerId);
        if (!containerEl) {
            console.error('Terminal container not found:', containerId);
            return;
        }

        term = new Terminal({
            cursorBlink: true,
            fontSize: 14,
            fontFamily: '"JetBrains Mono", "Fira Code", "Cascadia Code", Menlo, Monaco, monospace',
            theme: THEME,
            scrollback: 5000,
            convertEol: true,
            allowProposedApi: true
        });

        fitAddon = new FitAddon.FitAddon();
        webLinksAddon = new WebLinksAddon.WebLinksAddon();
        term.loadAddon(fitAddon);
        term.loadAddon(webLinksAddon);
    }

    /**
     * Open a WebSocket connection to /ws/terminal and wire up terminal I/O.
     * Automatically selects ws:// or wss:// based on page protocol.
     * Includes keepalive ping (30s) and reconnection with exponential backoff.
     */
    function connect() {
        if (connected) return;

        // Build WebSocket URL (auto ws/wss based on page protocol)
        var protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        var wsUrl = protocol + '//' + window.location.host + '/ws/terminal';

        socket = new WebSocket(wsUrl);

        socket.onopen = function() {
            connected = true;
            reconnectAttempts = 0;

            // Open terminal in container (must happen AFTER container is visible)
            if (!term._core) {
                // First connection — terminal not yet opened in DOM
                term.open(containerEl);
            }
            fitAddon.fit();

            // Send initial size so the PTY can set correct dimensions
            var dims = fitAddon.proposeDimensions();
            if (dims) {
                socket.send(JSON.stringify({
                    type: 'resize',
                    cols: dims.cols,
                    rows: dims.rows
                }));
            }

            // Terminal input → WebSocket
            term.onData(function(data) {
                if (socket.readyState === WebSocket.OPEN) {
                    socket.send(JSON.stringify({ type: 'input', data: data }));
                }
            });

            // Terminal resize → WebSocket
            term.onResize(function(size) {
                if (socket.readyState === WebSocket.OPEN) {
                    socket.send(JSON.stringify({
                        type: 'resize',
                        cols: size.cols,
                        rows: size.rows
                    }));
                }
            });

            // Keepalive ping every 30s
            pingInterval = setInterval(function() {
                if (socket.readyState === WebSocket.OPEN) {
                    socket.send(JSON.stringify({ type: 'ping' }));
                }
            }, 30000);

            term.write('\x1b[32mConnected\x1b[0m\r\n');
        };

        socket.onmessage = function(event) {
            try {
                var msg = JSON.parse(event.data);
                switch (msg.type) {
                    case 'output':
                        term.write(msg.data);
                        break;
                    case 'exit':
                        term.write('\r\n\x1b[31mProcess exited (code ' + msg.code + ')\x1b[0m\r\n');
                        connected = false;
                        break;
                    case 'error':
                        term.write('\r\n\x1b[31mError: ' + msg.message + '\x1b[0m\r\n');
                        break;
                    case 'pong':
                        break;  // Keepalive response — no action needed
                }
            } catch (e) {
                // Raw text fallback for non-JSON messages
                term.write(event.data);
            }
        };

        socket.onclose = function(event) {
            connected = false;
            clearInterval(pingInterval);

            if (event.code === 1008) {
                // Auth failure — do not attempt reconnection
                term.write('\r\n\x1b[31mAuthentication failed. Please log in.\x1b[0m\r\n');
                return;
            }

            if (reconnectAttempts < MAX_RECONNECT) {
                reconnectAttempts++;
                var delay = Math.min(1000 * Math.pow(2, reconnectAttempts), 10000);
                term.write('\r\n\x1b[33mDisconnected. Reconnecting in ' +
                    (delay / 1000) + 's... (attempt ' + reconnectAttempts + '/' + MAX_RECONNECT + ')\x1b[0m\r\n');
                setTimeout(connect, delay);
            } else {
                term.write('\r\n\x1b[31mDisconnected. Max reconnect attempts reached.\x1b[0m\r\n');
                term.write('\x1b[33mPress any key to reconnect...\x1b[0m\r\n');
                term.onData(function handler() {
                    term.off('data', handler);  // One-shot handler
                    reconnectAttempts = 0;
                    connect();
                });
            }
        };

        socket.onerror = function() {
            term.write('\r\n\x1b[31mWebSocket error\x1b[0m\r\n');
        };
    }

    /**
     * Close the WebSocket connection cleanly.
     * Stops keepalive ping. Does not dispose the terminal (can reconnect later).
     */
    function disconnect() {
        connected = false;
        clearInterval(pingInterval);
        if (socket) {
            socket.close();
            socket = null;
        }
    }

    /**
     * Full cleanup — disconnect WebSocket and dispose the terminal instance.
     * After dispose(), init() must be called again before reuse.
     */
    function dispose() {
        disconnect();
        if (term) {
            term.dispose();
            term = null;
        }
        fitAddon = null;
        webLinksAddon = null;
    }

    /**
     * Re-fit the terminal to its container dimensions.
     * Call after container resize or when modal becomes visible.
     */
    function fit() {
        if (fitAddon && term) {
            fitAddon.fit();
        }
    }

    /**
     * Focus the terminal input so keystrokes are captured.
     */
    function focus() {
        if (term) { term.focus(); }
    }

    return {
        init: init,
        connect: connect,
        disconnect: disconnect,
        dispose: dispose,
        fit: fit,
        focus: focus,
        isInitialized: function() { return term !== null; }
    };
})();
