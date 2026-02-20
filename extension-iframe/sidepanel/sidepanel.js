(function () {
    'use strict';

    var P = '[IframeSP]';
    console.log(P, '=== SIDEPANEL SCRIPT LOADING ===');

    var STORAGE_KEY = 'iframe_server_url';
    var LOAD_TIMEOUT_MS = 15000;

    var connectScreen  = document.getElementById('connect-screen');
    var loadingScreen  = document.getElementById('loading');
    var errorScreen    = document.getElementById('error');
    var frame          = document.getElementById('main-ui-frame');
    var loadingUrl     = document.getElementById('loading-url');
    var errorUrl       = document.getElementById('error-url');
    var connectError   = document.getElementById('connect-error');
    var customUrlInput = document.getElementById('custom-url');
    var loadTimer      = null;
    var currentUrl     = '';

    function showScreen(name) {
        connectScreen.style.display = name === 'connect' ? 'flex' : 'none';
        loadingScreen.style.display = name === 'loading' ? 'flex' : 'none';
        errorScreen.style.display   = name === 'error'   ? 'block' : 'none';
        frame.style.display         = name === 'iframe'  ? 'block' : 'none';
    }

    function normalizeUrl(raw) {
        var url = (raw || '').trim().replace(/\/+$/, '');
        if (!url) return '';
        if (!/^https?:\/\//i.test(url)) url = 'http://' + url;
        return url;
    }

    function saveUrl(url) {
        try { chrome.storage.local.set({ [STORAGE_KEY]: url }); } catch (_) {}
    }

    function connectTo(serverUrl) {
        var normalized = normalizeUrl(serverUrl);
        console.log(P, 'connectTo:', serverUrl, '→', normalized);
        if (!normalized) {
            connectError.textContent = 'Please enter a valid URL.';
            connectError.style.display = 'block';
            return;
        }
        connectError.style.display = 'none';
        currentUrl = normalized;
        saveUrl(normalized);

        var iframeSrc = normalized + '/interface/';
        console.log(P, 'setting iframe src:', iframeSrc);
        loadingUrl.textContent = normalized;
        errorUrl.textContent   = normalized;
        showScreen('loading');

        if (loadTimer) clearTimeout(loadTimer);
        loadTimer = setTimeout(function () {
            if (loadingScreen.style.display !== 'none') showScreen('error');
        }, LOAD_TIMEOUT_MS);

        frame.src = iframeSrc;
    }

    frame.addEventListener('load', function () {
        console.log(P, 'iframe load event. src:', frame.src);
        if (!frame.src) return;
        if (loadTimer) clearTimeout(loadTimer);
        showScreen('iframe');
    });

    frame.addEventListener('error', function () {
        console.log(P, 'iframe error event');
        if (loadTimer) clearTimeout(loadTimer);
        showScreen('error');
    });

    document.querySelectorAll('.preset-btn').forEach(function (btn) {
        btn.addEventListener('click', function () {
            connectTo(btn.getAttribute('data-url'));
        });
    });

    document.getElementById('connect-btn').addEventListener('click', function () {
        connectTo(customUrlInput.value);
    });
    customUrlInput.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') connectTo(customUrlInput.value);
    });

    document.getElementById('retry-btn').addEventListener('click', function () {
        connectTo(currentUrl);
    });
    document.getElementById('change-server-btn').addEventListener('click', function () {
        frame.src = '';
        if (loadTimer) clearTimeout(loadTimer);
        customUrlInput.value = currentUrl;
        showScreen('connect');
    });

    chrome.storage.local.get([STORAGE_KEY], function (result) {
        var saved = result && result[STORAGE_KEY];
        console.log(P, 'stored URL:', saved || '(none)');
        if (saved) {
            connectTo(saved);
        } else {
            showScreen('connect');
        }
    });

    console.log(P, '=== SIDEPANEL SCRIPT SETUP COMPLETE ===');
})();
