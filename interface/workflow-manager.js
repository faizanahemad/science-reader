/**
 * WorkflowManager - CRUD UI for workflows in the settings modal.
 * Uses backend endpoints: GET /ext/workflows/list, POST /ext/workflows/create,
 * PUT /ext/workflows/update, DELETE /ext/workflows/delete.
 * Selected workflow_id is available to the chat send flow.
 */
var WorkflowManager = (function() {
    'use strict';

    var _workflows = [];
    var _selectedWorkflowId = null;
    var _initialized = false;

    function _loadWorkflows() {
        $.get('/ext/workflows/list').done(function(data) {
            _workflows = data.workflows || data || [];
            _renderList();
        }).fail(function(xhr) {
            $('#workflow-list').html('<p class="text-danger">Failed to load workflows.</p>');
        });
    }

    function _renderList() {
        var $list = $('#workflow-list');
        $list.empty();

        if (_workflows.length === 0) {
            $list.html('<p class="text-muted small">No workflows configured.</p>');
            return;
        }

        _workflows.forEach(function(wf) {
            var isSelected = _selectedWorkflowId === wf.id;
            var card = '<div class="card mb-2 workflow-card' + (isSelected ? ' border-primary' : '') + '" data-id="' + wf.id + '">'
                + '<div class="card-body p-2 d-flex justify-content-between align-items-center">'
                + '<div class="flex-grow-1">'
                + '<strong class="small">' + $('<span>').text(wf.name || 'Untitled').html() + '</strong>'
                + (wf.description ? '<br><small class="text-muted">' + $('<span>').text(wf.description).html() + '</small>' : '')
                + '</div>'
                + '<div class="btn-group btn-group-sm">'
                + '<button class="btn btn-outline-primary workflow-select-btn" data-id="' + wf.id + '" title="' + (isSelected ? 'Deselect' : 'Select') + '">'
                + '<i class="fa ' + (isSelected ? 'fa-check-circle' : 'fa-circle-o') + '"></i>'
                + '</button>'
                + '<button class="btn btn-outline-secondary workflow-edit-btn" data-id="' + wf.id + '" title="Edit"><i class="fa fa-pencil"></i></button>'
                + '<button class="btn btn-outline-danger workflow-delete-btn" data-id="' + wf.id + '" title="Delete"><i class="fa fa-trash"></i></button>'
                + '</div></div></div>';
            $list.append(card);
        });
    }

    function _findWorkflow(id) {
        for (var i = 0; i < _workflows.length; i++) {
            if (_workflows[i].id === id) return _workflows[i];
        }
        return null;
    }

    function _createWorkflow() {
        var name = prompt('Workflow name:');
        if (!name) return;
        var description = prompt('Description (optional):') || '';

        $.ajax({
            url: '/ext/workflows/create',
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ name: name, description: description, steps: [] })
        }).done(function() {
            _loadWorkflows();
            if (typeof showToast === 'function') showToast('Workflow created', 'success');
        }).fail(function() {
            if (typeof showToast === 'function') showToast('Failed to create workflow', 'danger');
        });
    }

    function _editWorkflow(id) {
        var wf = _findWorkflow(id);
        if (!wf) return;
        var name = prompt('Workflow name:', wf.name);
        if (name === null) return;
        var description = prompt('Description:', wf.description || '') || '';

        $.ajax({
            url: '/ext/workflows/update',
            method: 'PUT',
            contentType: 'application/json',
            data: JSON.stringify({ id: id, name: name, description: description, steps: wf.steps || [] })
        }).done(function() {
            _loadWorkflows();
            if (typeof showToast === 'function') showToast('Workflow updated', 'success');
        }).fail(function() {
            if (typeof showToast === 'function') showToast('Failed to update workflow', 'danger');
        });
    }

    function _deleteWorkflow(id) {
        if (!confirm('Delete this workflow?')) return;
        $.ajax({
            url: '/ext/workflows/delete',
            method: 'DELETE',
            contentType: 'application/json',
            data: JSON.stringify({ id: id })
        }).done(function() {
            if (_selectedWorkflowId === id) _selectedWorkflowId = null;
            _loadWorkflows();
            if (typeof showToast === 'function') showToast('Workflow deleted', 'success');
        }).fail(function() {
            if (typeof showToast === 'function') showToast('Failed to delete workflow', 'danger');
        });
    }

    function _bindEvents() {
        $('#workflow-create-btn').on('click', function() { _createWorkflow(); });

        $(document).on('click', '.workflow-select-btn', function() {
            var id = $(this).data('id');
            if (_selectedWorkflowId === id) {
                _selectedWorkflowId = null;
            } else {
                _selectedWorkflowId = id;
            }
            _renderList();
        });

        $(document).on('click', '.workflow-edit-btn', function() {
            _editWorkflow($(this).data('id'));
        });

        $(document).on('click', '.workflow-delete-btn', function() {
            _deleteWorkflow($(this).data('id'));
        });
    }

    return {
        init: function() {
            if (_initialized) return;
            _initialized = true;
            _bindEvents();
            _loadWorkflows();
        },

        getSelectedWorkflowId: function() {
            return _selectedWorkflowId;
        },

        refresh: function() {
            _loadWorkflows();
        }
    };
})();
