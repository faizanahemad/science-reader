/**
 * ScriptManager - CRUD UI for custom scripts in the settings modal.
 * Uses backend endpoints: GET /ext/scripts/list, POST /ext/scripts/create,
 * PUT /ext/scripts/update, DELETE /ext/scripts/delete,
 * POST /ext/scripts/generate, POST /ext/scripts/validate.
 * "Test on Page" is grayed out when extension is unavailable.
 */
var ScriptManager = (function() {
    'use strict';

    var _scripts = [];
    var _initialized = false;

    function _loadScripts() {
        $.get('/ext/scripts/list').done(function(data) {
            _scripts = data.scripts || data || [];
            _renderList();
        }).fail(function() {
            $('#script-list').html('<p class="text-danger">Failed to load scripts.</p>');
        });
    }

    function _renderList() {
        var $list = $('#script-list');
        $list.empty();

        if (_scripts.length === 0) {
            $list.html('<p class="text-muted small">No custom scripts configured.</p>');
            return;
        }

        var extAvailable = typeof ExtensionBridge !== 'undefined' && ExtensionBridge.isAvailable;

        _scripts.forEach(function(script) {
            var card = '<div class="card mb-2 script-card" data-id="' + script.id + '">'
                + '<div class="card-body p-2">'
                + '<div class="d-flex justify-content-between align-items-center">'
                + '<div class="flex-grow-1">'
                + '<strong class="small">' + $('<span>').text(script.name || 'Untitled').html() + '</strong>'
                + (script.description ? '<br><small class="text-muted">' + $('<span>').text(script.description).html() + '</small>' : '')
                + '</div>'
                + '<div class="btn-group btn-group-sm">'
                + '<button class="btn btn-outline-info script-test-btn' + (extAvailable ? '' : ' disabled') + '" data-id="' + script.id + '" title="Test on Page"'
                + (extAvailable ? '' : ' disabled') + '><i class="fa fa-play"></i></button>'
                + '<button class="btn btn-outline-secondary script-validate-btn" data-id="' + script.id + '" title="Validate"><i class="fa fa-check"></i></button>'
                + '<button class="btn btn-outline-secondary script-edit-btn" data-id="' + script.id + '" title="Edit"><i class="fa fa-pencil"></i></button>'
                + '<button class="btn btn-outline-danger script-delete-btn" data-id="' + script.id + '" title="Delete"><i class="fa fa-trash"></i></button>'
                + '</div></div></div></div>';
            $list.append(card);
        });
    }

    function _findScript(id) {
        for (var i = 0; i < _scripts.length; i++) {
            if (_scripts[i].id === id) return _scripts[i];
        }
        return null;
    }

    function _createScript() {
        var name = prompt('Script name:');
        if (!name) return;
        var description = prompt('Description (optional):') || '';
        var code = prompt('JavaScript code:') || '';

        $.ajax({
            url: '/ext/scripts/create',
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ name: name, description: description, code: code })
        }).done(function() {
            _loadScripts();
            if (typeof showToast === 'function') showToast('Script created', 'success');
        }).fail(function() {
            if (typeof showToast === 'function') showToast('Failed to create script', 'danger');
        });
    }

    function _editScript(id) {
        var script = _findScript(id);
        if (!script) return;
        var name = prompt('Script name:', script.name);
        if (name === null) return;
        var description = prompt('Description:', script.description || '') || '';
        var code = prompt('JavaScript code:', script.code || '') || '';

        $.ajax({
            url: '/ext/scripts/update',
            method: 'PUT',
            contentType: 'application/json',
            data: JSON.stringify({ id: id, name: name, description: description, code: code })
        }).done(function() {
            _loadScripts();
            if (typeof showToast === 'function') showToast('Script updated', 'success');
        }).fail(function() {
            if (typeof showToast === 'function') showToast('Failed to update script', 'danger');
        });
    }

    function _deleteScript(id) {
        if (!confirm('Delete this script?')) return;
        $.ajax({
            url: '/ext/scripts/delete',
            method: 'DELETE',
            contentType: 'application/json',
            data: JSON.stringify({ id: id })
        }).done(function() {
            _loadScripts();
            if (typeof showToast === 'function') showToast('Script deleted', 'success');
        }).fail(function() {
            if (typeof showToast === 'function') showToast('Failed to delete script', 'danger');
        });
    }

    function _testScript(id) {
        if (!ExtensionBridge.isAvailable) {
            if (typeof showToast === 'function') showToast('Extension not available', 'warning');
            return;
        }
        var script = _findScript(id);
        if (!script || !script.code) return;

        ExtensionBridge.executeScript(null, script.code, 'test').then(function(result) {
            if (typeof showToast === 'function') showToast('Script executed successfully', 'success');
            console.log('Script test result:', result);
        }).catch(function(err) {
            if (typeof showToast === 'function') showToast('Script error: ' + (err.message || err), 'danger');
        });
    }

    function _validateScript(id) {
        var script = _findScript(id);
        if (!script) return;

        $.ajax({
            url: '/ext/scripts/validate',
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ id: id, code: script.code })
        }).done(function(data) {
            var valid = data.valid || data.success;
            if (valid) {
                if (typeof showToast === 'function') showToast('Script is valid', 'success');
            } else {
                if (typeof showToast === 'function') showToast('Validation errors: ' + (data.errors || data.message || 'Unknown'), 'warning');
            }
        }).fail(function() {
            if (typeof showToast === 'function') showToast('Validation request failed', 'danger');
        });
    }

    function _generateScript() {
        var description = prompt('Describe what the script should do:');
        if (!description) return;

        if (typeof showToast === 'function') showToast('Generating script…', 'info');

        $.ajax({
            url: '/ext/scripts/generate',
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ description: description })
        }).done(function(data) {
            if (data.script || data.code) {
                var name = data.name || 'Generated Script';
                var code = data.script || data.code || '';
                $.ajax({
                    url: '/ext/scripts/create',
                    method: 'POST',
                    contentType: 'application/json',
                    data: JSON.stringify({ name: name, description: description, code: code })
                }).done(function() {
                    _loadScripts();
                    if (typeof showToast === 'function') showToast('Script generated and saved', 'success');
                });
            } else {
                if (typeof showToast === 'function') showToast('Generation failed', 'danger');
            }
        }).fail(function() {
            if (typeof showToast === 'function') showToast('Failed to generate script', 'danger');
        });
    }

    function _bindEvents() {
        $('#script-create-btn').on('click', function() { _createScript(); });
        $('#script-generate-btn').on('click', function() { _generateScript(); });

        $(document).on('click', '.script-test-btn', function() {
            _testScript($(this).data('id'));
        });

        $(document).on('click', '.script-validate-btn', function() {
            _validateScript($(this).data('id'));
        });

        $(document).on('click', '.script-edit-btn', function() {
            _editScript($(this).data('id'));
        });

        $(document).on('click', '.script-delete-btn', function() {
            _deleteScript($(this).data('id'));
        });
    }

    return {
        init: function() {
            if (_initialized) return;
            _initialized = true;
            _bindEvents();
            _loadScripts();
        },

        refresh: function() {
            _loadScripts();
        }
    };
})();
