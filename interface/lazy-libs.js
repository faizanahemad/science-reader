/**
 * lazy-libs.js — On-demand loader for feature libraries
 *
 * Libraries that are only needed for specific features (code editing,
 * slide presentations, drawio diagrams, etc.) are loaded dynamically
 * on first use instead of eagerly in <head>.  Each loader returns a
 * cached Promise that resolves when all required scripts + CSS are
 * ready.  Subsequent calls return the same resolved Promise instantly.
 *
 * Item 7 of the rendering-performance audit.
 */
(function (window) {
    'use strict';

    var _promises = {};   // url → Promise (one per resource, deduped)
    var _groupCache = {}; // group-name → Promise (one per library group)

    // ------------------------------------------------------------
    // Low-level helpers
    // ------------------------------------------------------------

    /**
     * Dynamically load a single <script> tag.  Returns a cached Promise.
     */
    function loadScript(url) {
        if (_promises[url]) return _promises[url];
        _promises[url] = new Promise(function (resolve, reject) {
            var s = document.createElement('script');
            s.src = url;
            s.onload  = function () { resolve(); };
            s.onerror = function () { reject(new Error('Failed to load script: ' + url)); };
            document.head.appendChild(s);
        });
        return _promises[url];
    }

    /**
     * Dynamically inject a <link rel="stylesheet">.
     * CSS is non-render-blocking when injected via JS, so we resolve
     * immediately (the browser paints progressively as sheets arrive).
     */
    function loadCSS(url) {
        if (_promises[url]) return _promises[url];
        var link = document.createElement('link');
        link.rel  = 'stylesheet';
        link.href = url;
        document.head.appendChild(link);
        _promises[url] = Promise.resolve();
        return _promises[url];
    }

    // ------------------------------------------------------------
    // CodeMirror 5  (core → addons/modes in parallel)
    // ------------------------------------------------------------

    var CM_BASE = 'https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/';

    function _loadCodeMirror() {
        if (_groupCache.codemirror) return _groupCache.codemirror;
        // CSS (fire-and-forget — injected immediately)
        loadCSS(CM_BASE + 'codemirror.min.css');
        loadCSS(CM_BASE + 'theme/monokai.min.css');
        loadCSS(CM_BASE + 'addon/fold/foldgutter.css');

        // Core must load first; addons/modes depend on it.
        _groupCache.codemirror = loadScript(CM_BASE + 'codemirror.min.js').then(function () {
            return Promise.all([
                // Addons
                loadScript(CM_BASE + 'addon/edit/closebrackets.min.js'),
                loadScript(CM_BASE + 'addon/edit/matchbrackets.min.js'),
                loadScript(CM_BASE + 'addon/selection/active-line.min.js'),
                loadScript(CM_BASE + 'addon/fold/foldcode.min.js'),
                loadScript(CM_BASE + 'addon/fold/foldgutter.min.js'),
                loadScript(CM_BASE + 'addon/fold/indent-fold.min.js'),
                loadScript(CM_BASE + 'addon/mode/overlay.min.js'),
                // Modes
                loadScript(CM_BASE + 'mode/python/python.min.js'),
                loadScript(CM_BASE + 'mode/xml/xml.min.js'),
                loadScript(CM_BASE + 'mode/markdown/markdown.min.js'),
                loadScript(CM_BASE + 'mode/gfm/gfm.min.js'),
                loadScript(CM_BASE + 'mode/javascript/javascript.min.js'),
                loadScript(CM_BASE + 'mode/css/css.min.js'),
                loadScript(CM_BASE + 'mode/htmlmixed/htmlmixed.min.js')
            ]);
        }).then(function () {
            // Register the CodeMirror5 convenience wrapper (previously inline in HTML).
            _registerCodeMirror5Wrapper();
        });
        return _groupCache.codemirror;
    }

    /**
     * The window.CodeMirror5 factory — previously an inline <script> in
     * interface.html.  Moved here so it runs AFTER CodeMirror is loaded.
     */
    function _registerCodeMirror5Wrapper() {
        if (window.CodeMirror5) return;  // already registered
        window.CodeMirror5 = {
            createEditor: function (parent, doc) {
                try {
                    parent.innerHTML = '';
                    var textarea = document.createElement('textarea');
                    textarea.value = doc || '';
                    parent.appendChild(textarea);
                    var editor = CodeMirror.fromTextArea(textarea, {
                        mode: 'python',
                        theme: 'monokai',
                        lineNumbers: true,
                        indentUnit: 4,
                        lineWrapping: true,
                        autoCloseBrackets: true,
                        matchBrackets: true,
                        styleActiveLine: true,
                        foldGutter: true,
                        gutters: ['CodeMirror-linenumbers', 'CodeMirror-foldgutter'],
                        extraKeys: {
                            'Tab': function (cm) {
                                if (cm.somethingSelected()) { cm.indentSelection('add'); }
                                else { cm.replaceSelection('    '); }
                            },
                            'Shift-Tab': function (cm) { cm.indentSelection('subtract'); },
                            'Ctrl-/':    function (cm) { cm.toggleComment(); },
                            'Ctrl-F': 'findPersistent',
                            'Ctrl-H': 'replace'
                        }
                    });
                    editor.setSize(null, '70vh');
                    editor.getWrapperElement().style.fontSize = '12px';
                    return editor;
                } catch (error) {
                    console.error('CodeMirror5 wrapper: editor creation failed:', error);
                    throw error;
                }
            }
        };
    }

    // ------------------------------------------------------------
    // EasyMDE  (depends on CodeMirror)
    // ------------------------------------------------------------

    function _loadEasyMDE() {
        if (_groupCache.easymde) return _groupCache.easymde;
        _groupCache.easymde = _loadCodeMirror().then(function () {
            loadCSS('https://cdn.jsdelivr.net/npm/easymde/dist/easymde.min.css');
            return loadScript('https://cdn.jsdelivr.net/npm/easymde/dist/easymde.min.js');
        });
        return _groupCache.easymde;
    }

    // ------------------------------------------------------------
    // Reveal.js 4.3.1  (core → plugins in parallel)
    // ------------------------------------------------------------

    var REVEAL_BASE = 'https://cdn.jsdelivr.net/npm/reveal.js@4.3.1/';

    function _loadReveal() {
        if (_groupCache.reveal) return _groupCache.reveal;
        loadCSS(REVEAL_BASE + 'dist/reveal.css');
        loadCSS(REVEAL_BASE + 'dist/theme/white.css');
        _groupCache.reveal = loadScript(REVEAL_BASE + 'dist/reveal.js').then(function () {
            return Promise.all([
                loadScript(REVEAL_BASE + 'plugin/highlight/highlight.js'),
                loadScript(REVEAL_BASE + 'plugin/math/math.js')
            ]);
        });
        return _groupCache.reveal;
    }

    // ------------------------------------------------------------
    // drawio-renderer
    // ------------------------------------------------------------

    function _loadDrawio() {
        if (_groupCache.drawio) return _groupCache.drawio;
        _groupCache.drawio = loadScript(
            'https://laingsimon.github.io/render-diagram/drawio-renderer.js'
        );
        return _groupCache.drawio;
    }

    // ------------------------------------------------------------
    // Public API
    // ------------------------------------------------------------

    window.LazyLibs = {
        /** Load CodeMirror 5 core + all addons/modes + CM5 wrapper. */
        loadCodeMirror: _loadCodeMirror,
        /** Load EasyMDE (chains on CodeMirror). */
        loadEasyMDE:    _loadEasyMDE,
        /** Load Reveal.js core + highlight + math plugins. */
        loadReveal:     _loadReveal,
        /** Load drawio-renderer. */
        loadDrawio:     _loadDrawio,
        /** Low-level: load a single script by URL (cached). */
        loadScript:     loadScript,
        /** Low-level: inject a single CSS by URL (cached). */
        loadCSS:        loadCSS
    };

})(window);
