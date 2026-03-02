/**
 * Image Generation Manager
 *
 * Provides a modal UI for generating images via OpenRouter's image-capable
 * models (e.g. Nano Banana 2 / Gemini Flash). Supports optional conversation
 * context (summary, messages, memory pad, deep context) just like the AI
 * edit modals in file-browser and artefacts.
 */
var ImageGenManager = (function () {
    'use strict';

    var state = {
        busy: false,
        lastImages: [],   // array of data-URI strings
        lastText: '',
        lastPrompt: '',
        lastModel: '',
        inputImageDataUrl: null,   // base64 data URI of image to edit (optional)
        inputImageFilename: null,  // original filename of the uploaded input image
    };

    var MODELS = [
        { id: 'google/gemini-3.1-flash-image-preview', label: 'Nano Banana 2 (Recommended)' },
        { id: 'google/gemini-2.5-flash-image', label: 'Nano Banana (Original)' },
        { id: 'google/gemini-3-pro-image-preview', label: 'Nano Banana Pro' },
        { id: 'openai/gpt-5-image-mini', label: 'GPT-5 Image Mini' },
        { id: 'openai/gpt-5-image', label: 'GPT-5 Image' },
    ];

    // ── Helpers ──────────────────────────────────────────────────────────

    function _$(id) { return document.getElementById(id); }

    function _getConversationId() {
        return (typeof getConversationIdFromUrl === 'function') ? getConversationIdFromUrl() : null;
    }

    function _showToast(msg, type) {
        if (typeof showToast === 'function') showToast(msg, type || 'info');
        else console.log('[ImageGen]', type, msg);
    }

    // ── Init ─────────────────────────────────────────────────────────────

    function init() {
        var modal = _$('image-gen-modal');
        if (!modal) return;

        // Populate model dropdown
        var sel = _$('image-gen-model');
        if (sel && sel.options.length <= 1) {
            sel.innerHTML = '';
            MODELS.forEach(function (m) {
                var opt = document.createElement('option');
                opt.value = m.id;
                opt.textContent = m.label;
                sel.appendChild(opt);
            });
        }

        // Button handlers
        _bindClick('image-gen-cancel-btn', hide);
        _bindClick('image-gen-generate-btn', generate);
        _bindClick('image-gen-download-btn', downloadCurrent);
        _bindClick('image-gen-clear-btn', clearResult);

        // Backdrop click to close
        modal.addEventListener('click', function (e) {
            if (e.target === modal) hide();
        });

        // Escape key
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && modal.style.display === 'flex') {
                e.stopPropagation();
                hide();
            }
        });

        // Ctrl/Cmd+Enter to generate
        var textarea = _$('image-gen-prompt');
        if (textarea) {
            textarea.addEventListener('keydown', function (e) {
                if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
                    e.preventDefault();
                    generate();
                }
            });

            // On mobile, ensure tapping the textarea brings up the keyboard
            // even when Bootstrap focus-trapping is interfering.
            textarea.addEventListener('touchend', function (e) {
                _disableBootstrapFocusTrap();
                this.focus();
            });
        }

        // ── Image upload / drag-drop ──────────────────────────────────────
        _initUploadZone();

        console.log('[ImageGenManager] Initialized');
    }

    function _bindClick(id, fn) {
        var el = _$(id);
        if (el) el.addEventListener('click', fn);
    }

    // ── Upload zone ──────────────────────────────────────────────────────

    function _initUploadZone() {
        var area       = _$('image-gen-upload-area');
        var fileInput  = _$('image-gen-file-input');
        if (!area || !fileInput) return;

        // Click on area: if no image loaded → open picker; if collapsed strip → expand
        area.addEventListener('click', function (e) {
            var removeBtn     = _$('image-gen-remove-input');
            var removeBtnFull = _$('image-gen-remove-input-full');
            var collapseBtn   = _$('image-gen-input-collapse-btn');
            // Ignore clicks on action buttons (handled separately)
            if (e.target === removeBtn || e.target === removeBtnFull ||
                e.target === collapseBtn || (collapseBtn && collapseBtn.contains(e.target))) return;
            if (state.inputImageDataUrl) {
                // Toggle collapsed ↔ expanded
                _setInputImageExpanded(
                    _$('image-gen-input-collapsed').style.display !== 'none'
                );
            } else {
                fileInput.click();
            }
        });

        // File input change
        fileInput.addEventListener('change', function () {
            if (this.files && this.files[0]) _loadInputImage(this.files[0]);
        });

        // Remove button (collapsed strip)
        _bindClick('image-gen-remove-input', function (e) {
            e.stopPropagation();
            _clearInputImage();
        });
        // Remove button (expanded view)
        _bindClick('image-gen-remove-input-full', function (e) {
            e.stopPropagation();
            _clearInputImage();
        });
        // Collapse button (in expanded view)
        _bindClick('image-gen-input-collapse-btn', function (e) {
            e.stopPropagation();
            _setInputImageExpanded(false);
        });

        // Drag-and-drop
        area.addEventListener('dragover', function (e) {
            e.preventDefault();
            e.stopPropagation();
            area.classList.add('drag-over');
        });
        area.addEventListener('dragleave', function (e) {
            e.stopPropagation();
            area.classList.remove('drag-over');
        });
        area.addEventListener('drop', function (e) {
            e.preventDefault();
            e.stopPropagation();
            area.classList.remove('drag-over');
            var files = e.dataTransfer && e.dataTransfer.files;
            if (files && files[0] && files[0].type.startsWith('image/')) {
                _loadInputImage(files[0]);
            }
        });
    }

    function _loadInputImage(file) {
        var reader = new FileReader();
        reader.onload = function (e) {
            state.inputImageDataUrl = e.target.result;
            state.inputImageFilename = file.name || 'image';
            // Populate all image elements
            var mini  = _$('image-gen-input-mini');
            var thumb = _$('image-gen-input-thumb');
            if (mini)  mini.src  = e.target.result;
            if (thumb) thumb.src = e.target.result;
            var fnEl     = _$('image-gen-input-filename');
            var fnElFull = _$('image-gen-input-filename-full');
            if (fnEl)     fnEl.textContent     = file.name || '';
            if (fnElFull) fnElFull.textContent = file.name || '';
            // Hide placeholder, show collapsed strip (not expanded)
            var placeholder = _$('image-gen-upload-placeholder');
            if (placeholder) placeholder.style.display = 'none';
            _setInputImageExpanded(false);
            // Shrink the upload area border to match compact strip
            var area = _$('image-gen-upload-area');
            if (area) area.style.padding = '6px 10px';
        };
        reader.readAsDataURL(file);
    }

    /** Toggle between collapsed mini-strip and expanded full-thumbnail states. */
    function _setInputImageExpanded(expand) {
        var collapsed = _$('image-gen-input-collapsed');
        var expanded  = _$('image-gen-input-preview');
        if (collapsed) collapsed.style.display = expand ? 'none'  : 'flex';
        if (expanded)  expanded.style.display  = expand ? 'block' : 'none';
    }

    function _clearInputImage() {
        state.inputImageDataUrl = null;
        state.inputImageFilename = null;
        var fileInput = _$('image-gen-file-input');
        if (fileInput) fileInput.value = '';
        // Reset all elements
        var mini  = _$('image-gen-input-mini');
        var thumb = _$('image-gen-input-thumb');
        if (mini)  mini.src  = '';
        if (thumb) thumb.src = '';
        // Restore placeholder, hide both image states
        var placeholder = _$('image-gen-upload-placeholder');
        if (placeholder) placeholder.style.display = '';
        var collapsed = _$('image-gen-input-collapsed');
        var expanded  = _$('image-gen-input-preview');
        if (collapsed) collapsed.style.display = 'none';
        if (expanded)  expanded.style.display  = 'none';
        // Restore original upload area padding
        var area = _$('image-gen-upload-area');
        if (area) area.style.padding = '10px 12px';
    }

    // ── Show / Hide ──────────────────────────────────────────────────────

    function show() {
        var modal = _$('image-gen-modal');
        if (!modal) return;

        // Disable Bootstrap focus trapping on the settings modal underneath.
        // Bootstrap 4 modals call enforceFocus() which steals focus from any
        // overlay opened on top — this prevents the keyboard from appearing
        // on mobile when tapping the textarea.
        _disableBootstrapFocusTrap();

        // Check conversation availability for context checkboxes
        var convId = _getConversationId();
        var contextCheckboxes = [
            'image-gen-include-summary',
            'image-gen-include-messages',
            'image-gen-include-memory',
            'image-gen-deep-context'
        ];
        contextCheckboxes.forEach(function (cbId) {
            var cb = _$(cbId);
            if (!cb) return;
            if (convId) {
                cb.disabled = false;
                cb.closest('.form-check').style.opacity = '1';
            } else {
                cb.disabled = true;
                cb.checked = false;
                cb.closest('.form-check').style.opacity = '0.5';
            }
        });
        var histInput = _$('image-gen-history-count');
        if (histInput) histInput.disabled = !convId;

        modal.style.display = 'flex';

        // On mobile, the focus must happen after a slightly longer delay and
        // we need to ensure no Bootstrap modal steals it back.
        setTimeout(function () {
            var ta = _$('image-gen-prompt');
            if (ta) {
                ta.setAttribute('readonly', 'readonly');   // prevent zoom on iOS
                ta.focus();
                setTimeout(function () {
                    ta.removeAttribute('readonly');         // allow typing
                }, 100);
            }
        }, 150);
    }

    function hide() {
        var modal = _$('image-gen-modal');
        if (modal) modal.style.display = 'none';
        _setBusy(false);
        _restoreBootstrapFocusTrap();
    }

    // ── Bootstrap focus-trap management ──────────────────────────────────
    // Bootstrap 4's Modal binds a `focusin` handler on `document` that forces
    // focus back into the topmost .modal. When our custom overlay sits on top,
    // that handler steals focus from our inputs. We temporarily unbind it while
    // the image-gen modal is open, and restore it on close.

    var _savedFocusTrapHandler = null;

    function _disableBootstrapFocusTrap() {
        // Find the open Bootstrap modal underneath (chat-settings or opencode-settings)
        var openModals = document.querySelectorAll('.modal.show');
        openModals.forEach(function (m) {
            try {
                var modalData = $(m).data('bs.modal');
                if (modalData && modalData._focusHandler) {
                    // Bootstrap 4: _focusHandler is the bound focusin listener
                    _savedFocusTrapHandler = { el: m, data: modalData };
                    $(document).off('focusin.bs.modal');
                }
            } catch (e) { /* ignore */ }
        });
        // Fallback: just brute-force remove the focusin.bs.modal event
        if (!_savedFocusTrapHandler) {
            try { $(document).off('focusin.bs.modal'); } catch (e) {}
        }
    }

    function _restoreBootstrapFocusTrap() {
        // Re-trigger enforceFocus on the original modal if it's still open
        if (_savedFocusTrapHandler) {
            var modalData = _savedFocusTrapHandler.data;
            try {
                if (modalData && typeof modalData._enforceFocus === 'function') {
                    modalData._enforceFocus();
                }
            } catch (e) { /* ignore */ }
            _savedFocusTrapHandler = null;
        }
    }

    // ── Busy state ───────────────────────────────────────────────────────

    function _setBusy(busy) {
        state.busy = busy;
        var btn = _$('image-gen-generate-btn');
        var spinner = _$('image-gen-spinner');
        if (btn) btn.disabled = busy;
        if (spinner) spinner.style.display = busy ? 'inline-block' : 'none';
    }

    // ── Generate ─────────────────────────────────────────────────────────

    function generate() {
        if (state.busy) return;

        var prompt = (_$('image-gen-prompt') || {}).value;
        prompt = (prompt || '').trim();
        if (!prompt) {
            _showToast('Please enter a prompt.', 'warning');
            return;
        }

        var modelSel = _$('image-gen-model');
        var model = modelSel ? modelSel.value : MODELS[0].id;

        var convId = _getConversationId();
        var payload = {
            prompt: prompt,
            model: model,
            include_summary: !!(_$('image-gen-include-summary') || {}).checked,
            include_messages: !!(_$('image-gen-include-messages') || {}).checked,
            include_memory_pad: !!(_$('image-gen-include-memory') || {}).checked,
            history_count: parseInt((_$('image-gen-history-count') || {}).value || '10', 10),
            deep_context: !!(_$('image-gen-deep-context') || {}).checked,
            better_context: !!(_$('image-gen-better-context') || {}).checked,
        };
        // Attach input image for editing if one was uploaded
        if (state.inputImageDataUrl) {
            payload.input_image = state.inputImageDataUrl;
        }

        var anyContext = payload.include_summary || payload.include_messages ||
                         payload.include_memory_pad || payload.deep_context;
        if (convId && anyContext) {
            payload.conversation_id = convId;
        }

        _setBusy(true);
        _clearPreview();
        _$('image-gen-status').textContent = 'Generating image...';
        _$('image-gen-status').style.display = 'block';

        $.ajax({
            url: '/api/generate-image',
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify(payload),
            timeout: 150000,  // 2.5 min
        })
        .done(function (resp) {
            _setBusy(false);
            _$('image-gen-status').style.display = 'none';

            if (resp.status === 'error') {
                _showToast(resp.error || 'Image generation failed.', 'error');
                return;
            }

            var images = resp.images || [];
            state.lastImages = images;
            state.lastText = resp.text || '';
            state.lastPrompt = prompt;
            state.lastModel = resp.model || model;

            if (resp.warning) {
                _showToast(resp.warning, 'warning');
            }

            if (images.length === 0) {
                _$('image-gen-status').textContent = 'No images returned. Try a different prompt.';
                _$('image-gen-status').style.display = 'block';
                return;
            }

            _renderPreview(images, resp.text, resp.refined_prompt);
            _showToast('Image generated successfully!', 'success');
        })
        .fail(function (xhr) {
            _setBusy(false);
            _$('image-gen-status').style.display = 'none';
            var msg = 'Image generation request failed.';
            try { msg = JSON.parse(xhr.responseText).error || msg; } catch (e) {}
            _showToast(msg, 'error');
        });
    }

    // ── Preview ──────────────────────────────────────────────────────────

    function _clearPreview() {
        var container = _$('image-gen-preview');
        if (container) container.innerHTML = '';
        var dlBtn = _$('image-gen-download-btn');
        if (dlBtn) dlBtn.style.display = 'none';
        var clrBtn = _$('image-gen-clear-btn');
        if (clrBtn) clrBtn.style.display = 'none';
    }

    function _renderPreview(images, text, refinedPrompt) {
        var container = _$('image-gen-preview');
        if (!container) return;
        container.innerHTML = '';

        // Show refined prompt if better-context was used
        if (refinedPrompt) {
            var rpDiv = document.createElement('div');
            rpDiv.style.cssText = 'background:#f0f7ff; border:1px solid #bee3f8; border-radius:6px; padding:8px 10px; margin-bottom:10px; font-size:0.82rem;';
            rpDiv.innerHTML = '<strong style="color:#2b6cb0;">Refined prompt:</strong> ' +
                refinedPrompt.replace(/</g, '&lt;').replace(/>/g, '&gt;');
            container.appendChild(rpDiv);
        }

        images.forEach(function (dataUrl, idx) {
            var wrapper = document.createElement('div');
            wrapper.style.cssText = 'text-align:center; margin-bottom:12px;';

            var img = document.createElement('img');
            img.src = dataUrl;
            img.alt = 'Generated image ' + (idx + 1);
            img.style.cssText = 'max-width:100%; max-height:60vh; border-radius:6px; border:1px solid #dee2e6; cursor:pointer;';
            img.title = 'Click to open in new tab';
            img.addEventListener('click', function () {
                var w = window.open('');
                if (w) { w.document.write('<img src="' + dataUrl + '" style="max-width:100%;">'); }
            });
            wrapper.appendChild(img);
            container.appendChild(wrapper);
        });

        if (text) {
            var textDiv = document.createElement('div');
            textDiv.className = 'text-muted small mt-2';
            textDiv.textContent = text;
            container.appendChild(textDiv);
        }

        // Show download + clear buttons
        var dlBtn = _$('image-gen-download-btn');
        if (dlBtn) dlBtn.style.display = 'inline-block';
        var clrBtn = _$('image-gen-clear-btn');
        if (clrBtn) clrBtn.style.display = 'inline-block';
    }

    function clearResult() {
        state.lastImages = [];
        state.lastText = '';
        _clearPreview();
        _clearInputImage();
    }

    // ── Download ─────────────────────────────────────────────────────────

    function downloadCurrent() {
        if (!state.lastImages.length) {
            _showToast('No image to download.', 'warning');
            return;
        }
        state.lastImages.forEach(function (dataUrl, idx) {
            var a = document.createElement('a');
            // Handle data URI or regular URL
            if (dataUrl.startsWith('data:')) {
                a.href = dataUrl;
            } else {
                a.href = dataUrl;
                a.target = '_blank';
            }
            var timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
            a.download = 'generated-image-' + timestamp + (idx > 0 ? '-' + (idx + 1) : '') + '.png';
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
        });
        _showToast('Download started.', 'success');
    }

    // ── Public API ───────────────────────────────────────────────────────

    return {
        init: init,
        show: show,
        hide: hide,
    };
})();

// Auto-init when DOM is ready
$(function () {
    ImageGenManager.init();
});
