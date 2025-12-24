/**
 * PKB (Personal Knowledge Base) Manager
 * 
 * This module provides JavaScript functionality for managing the Personal Knowledge Base
 * including API calls, UI rendering, and memory update proposal handling.
 * 
 * Dependencies:
 * - jQuery
 * - Bootstrap (for modal handling)
 */

var PKBManager = (function() {
    'use strict';
    
    // ===========================================================================
    // State
    // ===========================================================================
    
    var currentPage = 0;
    var pageSize = 20;
    var currentPlanId = null;
    var currentProposals = [];
    
    // ===========================================================================
    // API Functions
    // ===========================================================================
    
    /**
     * List claims with optional filters.
     * @param {Object} filters - Optional filters (claim_type, context_domain, status)
     * @param {number} limit - Max results (default: 20)
     * @param {number} offset - Pagination offset (default: 0)
     * @returns {Promise} jQuery AJAX promise
     */
    function listClaims(filters, limit, offset) {
        filters = filters || {};
        limit = limit || pageSize;
        offset = offset || 0;
        
        var queryParams = new URLSearchParams();
        if (filters.claim_type) queryParams.append('claim_type', filters.claim_type);
        if (filters.context_domain) queryParams.append('context_domain', filters.context_domain);
        if (filters.status) queryParams.append('status', filters.status);
        queryParams.append('limit', limit);
        queryParams.append('offset', offset);
        
        return $.ajax({
            url: '/pkb/claims?' + queryParams.toString(),
            method: 'GET',
            dataType: 'json'
        });
    }
    
    /**
     * Add a new claim.
     * @param {Object} claim - Claim data
     * @returns {Promise} jQuery AJAX promise
     */
    function addClaim(claim) {
        return $.ajax({
            url: '/pkb/claims',
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify(claim),
            dataType: 'json'
        });
    }
    
    /**
     * Edit an existing claim.
     * @param {string} claimId - Claim ID
     * @param {Object} updates - Fields to update
     * @returns {Promise} jQuery AJAX promise
     */
    function editClaim(claimId, updates) {
        return $.ajax({
            url: '/pkb/claims/' + claimId,
            method: 'PUT',
            contentType: 'application/json',
            data: JSON.stringify(updates),
            dataType: 'json'
        });
    }
    
    /**
     * Delete (retract) a claim.
     * @param {string} claimId - Claim ID
     * @returns {Promise} jQuery AJAX promise
     */
    function deleteClaim(claimId) {
        return $.ajax({
            url: '/pkb/claims/' + claimId,
            method: 'DELETE',
            dataType: 'json'
        });
    }
    
    /**
     * Search claims.
     * @param {string} query - Search query
     * @param {Object} options - Optional options (strategy, k, filters)
     * @returns {Promise} jQuery AJAX promise
     */
    function searchClaims(query, options) {
        options = options || {};
        return $.ajax({
            url: '/pkb/search',
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({
                query: query,
                strategy: options.strategy || 'hybrid',
                k: options.k || 20,
                filters: options.filters || {}
            }),
            dataType: 'json'
        });
    }
    
    /**
     * List entities.
     * @param {string} entityType - Optional entity type filter
     * @returns {Promise} jQuery AJAX promise
     */
    function listEntities(entityType) {
        var url = '/pkb/entities';
        if (entityType) {
            url += '?entity_type=' + encodeURIComponent(entityType);
        }
        return $.ajax({
            url: url,
            method: 'GET',
            dataType: 'json'
        });
    }
    
    /**
     * List tags.
     * @returns {Promise} jQuery AJAX promise
     */
    function listTags() {
        return $.ajax({
            url: '/pkb/tags',
            method: 'GET',
            dataType: 'json'
        });
    }
    
    /**
     * List open conflicts.
     * @returns {Promise} jQuery AJAX promise
     */
    function listConflicts() {
        return $.ajax({
            url: '/pkb/conflicts',
            method: 'GET',
            dataType: 'json'
        });
    }
    
    /**
     * Resolve a conflict.
     * @param {string} conflictId - Conflict set ID
     * @param {string} resolutionNotes - Resolution notes
     * @param {string} winningClaimId - Optional winning claim ID
     * @returns {Promise} jQuery AJAX promise
     */
    function resolveConflict(conflictId, resolutionNotes, winningClaimId) {
        return $.ajax({
            url: '/pkb/conflicts/' + conflictId + '/resolve',
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({
                resolution_notes: resolutionNotes,
                winning_claim_id: winningClaimId
            }),
            dataType: 'json'
        });
    }
    
    /**
     * Propose memory updates from a conversation turn.
     * @param {string} conversationSummary - Summary of recent conversation
     * @param {string} userMessage - User's latest message
     * @param {string} assistantMessage - Optional assistant response
     * @returns {Promise} jQuery AJAX promise
     */
    function proposeUpdates(conversationSummary, userMessage, assistantMessage) {
        return $.ajax({
            url: '/pkb/propose_updates',
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({
                conversation_summary: conversationSummary || '',
                user_message: userMessage,
                assistant_message: assistantMessage || ''
            }),
            dataType: 'json'
        });
    }
    
    /**
     * Execute approved memory updates.
     * @param {string} planId - Plan ID from proposeUpdates
     * @param {Array<number>} approvedIndices - Indices of approved actions
     * @returns {Promise} jQuery AJAX promise
     */
    function executeUpdates(planId, approvedIndices) {
        return $.ajax({
            url: '/pkb/execute_updates',
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({
                plan_id: planId,
                approved_indices: approvedIndices
            }),
            dataType: 'json'
        });
    }
    
    // ===========================================================================
    // UI Rendering Functions
    // ===========================================================================
    
    /**
     * Render a claim type badge.
     * @param {string} claimType - The claim type
     * @returns {string} HTML for the badge
     */
    function renderClaimTypeBadge(claimType) {
        var colors = {
            'fact': 'primary',
            'preference': 'info',
            'decision': 'success',
            'task': 'warning',
            'reminder': 'danger',
            'habit': 'secondary',
            'memory': 'dark',
            'observation': 'light'
        };
        var color = colors[claimType] || 'secondary';
        return '<span class="badge badge-' + color + '">' + claimType + '</span>';
    }
    
    /**
     * Render a claim card.
     * @param {Object} claim - The claim object
     * @returns {string} HTML for the claim card
     */
    function renderClaimCard(claim) {
        var statusClass = claim.status === 'contested' ? 'border-warning' : '';
        var contestedBadge = claim.status === 'contested' ? 
            '<span class="badge badge-warning ml-2">Contested</span>' : '';
        
        return '<div class="list-group-item ' + statusClass + '" data-claim-id="' + claim.claim_id + '">' +
            '<div class="d-flex w-100 justify-content-between align-items-start">' +
                '<div class="flex-grow-1">' +
                    '<p class="mb-1">' + escapeHtml(claim.statement) + '</p>' +
                    '<small class="text-muted">' +
                        renderClaimTypeBadge(claim.claim_type) + ' ' +
                        '<span class="badge badge-outline-secondary">' + claim.context_domain + '</span>' +
                        contestedBadge +
                    '</small>' +
                '</div>' +
                '<div class="btn-group btn-group-sm">' +
                    '<button class="btn btn-outline-primary pkb-edit-claim" data-claim-id="' + claim.claim_id + '" title="Edit">' +
                        '<i class="bi bi-pencil"></i>' +
                    '</button>' +
                    '<button class="btn btn-outline-danger pkb-delete-claim" data-claim-id="' + claim.claim_id + '" title="Delete">' +
                        '<i class="bi bi-trash"></i>' +
                    '</button>' +
                '</div>' +
            '</div>' +
            '<small class="text-muted">Updated: ' + formatDate(claim.updated_at) + '</small>' +
        '</div>';
    }
    
    /**
     * Render the claims list.
     * @param {Array} claims - Array of claim objects
     */
    function renderClaimsList(claims) {
        var $list = $('#pkb-claims-list');
        
        if (!claims || claims.length === 0) {
            $list.html(
                '<div class="text-center text-muted py-4">' +
                    '<i class="bi bi-inbox" style="font-size: 2rem;"></i>' +
                    '<p>No memories found. Add your first one!</p>' +
                '</div>'
            );
            return;
        }
        
        var html = claims.map(renderClaimCard).join('');
        $list.html(html);
        
        // Bind edit/delete handlers
        $list.find('.pkb-edit-claim').on('click', function() {
            var claimId = $(this).data('claim-id');
            openEditClaimModal(claimId);
        });
        
        $list.find('.pkb-delete-claim').on('click', function() {
            var claimId = $(this).data('claim-id');
            if (confirm('Are you sure you want to delete this memory?')) {
                deleteClaimAndRefresh(claimId);
            }
        });
    }
    
    /**
     * Render an entity card.
     * @param {Object} entity - The entity object
     * @returns {string} HTML for the entity card
     */
    function renderEntityCard(entity) {
        var typeIcons = {
            'person': 'bi-person',
            'org': 'bi-building',
            'place': 'bi-geo-alt',
            'topic': 'bi-bookmark',
            'project': 'bi-folder',
            'system': 'bi-gear',
            'other': 'bi-circle'
        };
        var icon = typeIcons[entity.entity_type] || 'bi-circle';
        
        return '<div class="list-group-item">' +
            '<i class="bi ' + icon + ' mr-2"></i>' +
            '<strong>' + escapeHtml(entity.name) + '</strong> ' +
            '<span class="badge badge-secondary">' + entity.entity_type + '</span>' +
        '</div>';
    }
    
    /**
     * Render the entities list.
     * @param {Array} entities - Array of entity objects
     */
    function renderEntitiesList(entities) {
        var $list = $('#pkb-entities-list');
        
        if (!entities || entities.length === 0) {
            $list.html(
                '<div class="text-center text-muted py-4">' +
                    '<i class="bi bi-person-badge" style="font-size: 2rem;"></i>' +
                    '<p>No entities found.</p>' +
                '</div>'
            );
            return;
        }
        
        var html = entities.map(renderEntityCard).join('');
        $list.html(html);
    }
    
    /**
     * Render a tag chip.
     * @param {Object} tag - The tag object
     * @returns {string} HTML for the tag
     */
    function renderTagChip(tag) {
        return '<span class="badge badge-pill badge-info m-1" style="font-size: 0.9rem;">' +
            '<i class="bi bi-tag mr-1"></i>' + escapeHtml(tag.name) +
        '</span>';
    }
    
    /**
     * Render the tags list.
     * @param {Array} tags - Array of tag objects
     */
    function renderTagsList(tags) {
        var $list = $('#pkb-tags-list');
        
        if (!tags || tags.length === 0) {
            $list.html(
                '<div class="text-center text-muted py-4">' +
                    '<i class="bi bi-tag" style="font-size: 2rem;"></i>' +
                    '<p>No tags found.</p>' +
                '</div>'
            );
            return;
        }
        
        var html = '<div class="d-flex flex-wrap p-2">' + 
            tags.map(renderTagChip).join('') + 
        '</div>';
        $list.html(html);
    }
    
    /**
     * Render a conflict card.
     * @param {Object} conflict - The conflict set object
     * @returns {string} HTML for the conflict card
     */
    function renderConflictCard(conflict) {
        return '<div class="list-group-item list-group-item-warning">' +
            '<div class="d-flex w-100 justify-content-between">' +
                '<strong><i class="bi bi-exclamation-triangle mr-2"></i>Conflict</strong>' +
                '<span class="badge badge-warning">' + conflict.member_claim_ids.length + ' claims</span>' +
            '</div>' +
            '<p class="mb-1 small">' + 
                (conflict.resolution_notes || 'No resolution notes') + 
            '</p>' +
            '<button class="btn btn-sm btn-outline-primary pkb-resolve-conflict" data-conflict-id="' + conflict.conflict_set_id + '">' +
                'Resolve' +
            '</button>' +
        '</div>';
    }
    
    /**
     * Render the conflicts list.
     * @param {Array} conflicts - Array of conflict objects
     */
    function renderConflictsList(conflicts) {
        var $list = $('#pkb-conflicts-list');
        
        if (!conflicts || conflicts.length === 0) {
            $list.html(
                '<div class="text-center text-muted py-4">' +
                    '<i class="bi bi-check-circle" style="font-size: 2rem; color: green;"></i>' +
                    '<p>No conflicts! All your memories are consistent.</p>' +
                '</div>'
            );
            return;
        }
        
        var html = conflicts.map(renderConflictCard).join('');
        $list.html(html);
    }
    
    // ===========================================================================
    // Memory Proposal Functions
    // ===========================================================================
    
    /**
     * Check for memory updates and show modal if any.
     * @param {string} conversationSummary - Conversation summary
     * @param {string} userMessage - User message
     * @param {string} assistantMessage - Optional assistant message
     */
    function checkMemoryUpdates(conversationSummary, userMessage, assistantMessage) {
        proposeUpdates(conversationSummary, userMessage, assistantMessage)
            .done(function(response) {
                if (response.has_updates && response.proposed_actions && response.proposed_actions.length > 0) {
                    currentPlanId = response.plan_id;
                    currentProposals = response.proposed_actions;
                    showMemoryProposalModal(response);
                }
            })
            .fail(function(err) {
                console.error('Failed to check memory updates:', err);
            });
    }
    
    /**
     * Show the memory proposal modal.
     * @param {Object} proposals - Proposal data from API
     */
    function showMemoryProposalModal(proposals) {
        var $list = $('#memory-proposal-list');
        var html = '';
        
        proposals.proposed_actions.forEach(function(action, index) {
            var actionLabel = action.action === 'edit' ? 
                '<span class="badge badge-warning">Update</span>' : 
                '<span class="badge badge-success">New</span>';
            
            html += '<div class="form-check mb-3 p-2 bg-light rounded">' +
                '<input class="form-check-input memory-proposal-checkbox" type="checkbox" ' +
                    'value="' + index + '" id="proposal-' + index + '" checked>' +
                '<label class="form-check-label" for="proposal-' + index + '">' +
                    actionLabel + ' ' +
                    '<strong>' + escapeHtml(action.statement) + '</strong>' +
                    '<br><small class="text-muted">' + 
                        action.claim_type + ' / ' + action.context_domain +
                    '</small>' +
                '</label>' +
            '</div>';
        });
        
        $list.html(html);
        $('#memory-proposal-plan-id').val(proposals.plan_id);
        
        if (proposals.user_prompt) {
            $('#memory-proposal-intro').text(proposals.user_prompt);
        }
        
        $('#memory-proposal-modal').modal('show');
    }
    
    /**
     * Save the selected memory proposals.
     */
    function saveSelectedProposals() {
        var planId = $('#memory-proposal-plan-id').val();
        var approvedIndices = [];
        
        $('.memory-proposal-checkbox:checked').each(function() {
            approvedIndices.push(parseInt($(this).val(), 10));
        });
        
        if (approvedIndices.length === 0) {
            $('#memory-proposal-modal').modal('hide');
            return;
        }
        
        executeUpdates(planId, approvedIndices)
            .done(function(response) {
                console.log('Memory updates saved:', response);
                $('#memory-proposal-modal').modal('hide');
                
                // Show success message
                if (response.executed_count > 0) {
                    showToast('Saved ' + response.executed_count + ' memories!', 'success');
                }
            })
            .fail(function(err) {
                console.error('Failed to save memory updates:', err);
                showToast('Failed to save memories. Please try again.', 'error');
            });
    }
    
    // ===========================================================================
    // Modal Management
    // ===========================================================================
    
    /**
     * Open the PKB modal and load data.
     */
    function openPKBModal() {
        loadClaims();
        $('#pkb-modal').modal('show');
    }
    
    /**
     * Open the add claim modal.
     */
    function openAddClaimModal() {
        $('#pkb-claim-edit-id').val('');
        $('#pkb-claim-statement').val('');
        $('#pkb-claim-type').val('preference');
        $('#pkb-claim-domain').val('personal');
        $('#pkb-claim-tags').val('');
        $('#pkb-claim-edit-title').text('Add Memory');
        $('#pkb-claim-edit-modal').modal('show');
    }
    
    /**
     * Open the edit claim modal.
     * @param {string} claimId - Claim ID to edit
     */
    function openEditClaimModal(claimId) {
        // Fetch the claim first
        $.ajax({
            url: '/pkb/claims/' + claimId,
            method: 'GET',
            dataType: 'json'
        }).done(function(response) {
            var claim = response.claim;
            $('#pkb-claim-edit-id').val(claim.claim_id);
            $('#pkb-claim-statement').val(claim.statement);
            $('#pkb-claim-type').val(claim.claim_type);
            $('#pkb-claim-domain').val(claim.context_domain);
            $('#pkb-claim-tags').val(''); // Tags would need separate fetch
            $('#pkb-claim-edit-title').text('Edit Memory');
            $('#pkb-claim-edit-modal').modal('show');
        }).fail(function(err) {
            console.error('Failed to fetch claim:', err);
            showToast('Failed to load memory for editing.', 'error');
        });
    }
    
    /**
     * Save the claim (add or edit).
     */
    function saveClaim() {
        var claimId = $('#pkb-claim-edit-id').val();
        var statement = $('#pkb-claim-statement').val().trim();
        var claimType = $('#pkb-claim-type').val();
        var contextDomain = $('#pkb-claim-domain').val();
        var tagsStr = $('#pkb-claim-tags').val().trim();
        
        if (!statement) {
            showToast('Please enter something to remember.', 'warning');
            return;
        }
        
        var tags = tagsStr ? tagsStr.split(',').map(function(t) { return t.trim(); }) : [];
        
        var promise;
        if (claimId) {
            // Edit
            promise = editClaim(claimId, {
                statement: statement,
                claim_type: claimType,
                context_domain: contextDomain
            });
        } else {
            // Add
            promise = addClaim({
                statement: statement,
                claim_type: claimType,
                context_domain: contextDomain,
                tags: tags,
                auto_extract: false
            });
        }
        
        promise.done(function(response) {
            if (response.success || response.claim) {
                $('#pkb-claim-edit-modal').modal('hide');
                loadClaims();
                showToast('Memory saved!', 'success');
            } else {
                showToast(response.error || 'Failed to save memory.', 'error');
            }
        }).fail(function(err) {
            console.error('Failed to save claim:', err);
            showToast('Failed to save memory. Please try again.', 'error');
        });
    }
    
    /**
     * Delete a claim and refresh the list.
     * @param {string} claimId - Claim ID to delete
     */
    function deleteClaimAndRefresh(claimId) {
        deleteClaim(claimId)
            .done(function(response) {
                if (response.success) {
                    loadClaims();
                    showToast('Memory deleted.', 'success');
                } else {
                    showToast(response.error || 'Failed to delete memory.', 'error');
                }
            })
            .fail(function(err) {
                console.error('Failed to delete claim:', err);
                showToast('Failed to delete memory. Please try again.', 'error');
            });
    }
    
    // ===========================================================================
    // Data Loading Functions
    // ===========================================================================
    
    /**
     * Load claims with current filters.
     */
    function loadClaims() {
        var filters = {
            claim_type: $('#pkb-filter-type').val() || undefined,
            context_domain: $('#pkb-filter-domain').val() || undefined,
            status: $('#pkb-filter-status').val() || 'active'
        };
        
        listClaims(filters, pageSize, currentPage * pageSize)
            .done(function(response) {
                renderClaimsList(response.claims);
                $('#pkb-claims-count').text(response.count + ' claims');
                
                // Update pagination
                $('#pkb-prev-page').prop('disabled', currentPage === 0);
                $('#pkb-next-page').prop('disabled', response.count < pageSize);
            })
            .fail(function(err) {
                console.error('Failed to load claims:', err);
                renderClaimsList([]);
            });
    }
    
    /**
     * Load entities.
     */
    function loadEntities() {
        listEntities()
            .done(function(response) {
                renderEntitiesList(response.entities);
            })
            .fail(function(err) {
                console.error('Failed to load entities:', err);
                renderEntitiesList([]);
            });
    }
    
    /**
     * Load tags.
     */
    function loadTags() {
        listTags()
            .done(function(response) {
                renderTagsList(response.tags);
            })
            .fail(function(err) {
                console.error('Failed to load tags:', err);
                renderTagsList([]);
            });
    }
    
    /**
     * Load conflicts.
     */
    function loadConflicts() {
        listConflicts()
            .done(function(response) {
                renderConflictsList(response.conflicts);
            })
            .fail(function(err) {
                console.error('Failed to load conflicts:', err);
                renderConflictsList([]);
            });
    }
    
    /**
     * Perform a search.
     */
    function performSearch() {
        var query = $('#pkb-search-input').val().trim();
        if (!query) {
            loadClaims();
            return;
        }
        
        searchClaims(query)
            .done(function(response) {
                var claims = response.results.map(function(r) { return r.claim; });
                renderClaimsList(claims);
                $('#pkb-claims-count').text(response.count + ' results');
            })
            .fail(function(err) {
                console.error('Search failed:', err);
                renderClaimsList([]);
            });
    }
    
    // ===========================================================================
    // Utility Functions
    // ===========================================================================
    
    /**
     * Escape HTML to prevent XSS.
     * @param {string} text - Text to escape
     * @returns {string} Escaped HTML
     */
    function escapeHtml(text) {
        if (!text) return '';
        var div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
    
    /**
     * Format an ISO date string.
     * @param {string} isoDate - ISO date string
     * @returns {string} Formatted date
     */
    function formatDate(isoDate) {
        if (!isoDate) return '';
        try {
            var date = new Date(isoDate);
            return date.toLocaleDateString() + ' ' + date.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'});
        } catch (e) {
            return isoDate;
        }
    }
    
    /**
     * Show a toast notification.
     * @param {string} message - Message to show
     * @param {string} type - Type (success, error, warning, info)
     */
    function showToast(message, type) {
        // Simple implementation - can be enhanced with actual toast library
        type = type || 'info';
        var alertClass = {
            'success': 'alert-success',
            'error': 'alert-danger',
            'warning': 'alert-warning',
            'info': 'alert-info'
        }[type] || 'alert-info';
        
        var $toast = $('<div class="alert ' + alertClass + ' alert-dismissible fade show" role="alert" ' +
            'style="position: fixed; top: 20px; right: 20px; z-index: 9999; max-width: 400px;">' +
            message +
            '<button type="button" class="close" data-dismiss="alert">&times;</button>' +
        '</div>');
        
        $('body').append($toast);
        
        setTimeout(function() {
            $toast.alert('close');
        }, 3000);
    }
    
    // ===========================================================================
    // Initialization
    // ===========================================================================
    
    /**
     * Initialize event handlers.
     */
    function init() {
        // PKB Modal button
        $(document).on('click', '#settings-pkb-modal-open-button', function() {
            openPKBModal();
        });
        
        // Add claim button
        $(document).on('click', '#pkb-add-claim-btn', function() {
            openAddClaimModal();
        });
        
        // Save claim button
        $(document).on('click', '#pkb-claim-save-btn', function() {
            saveClaim();
        });
        
        // Search button and enter key
        $(document).on('click', '#pkb-search-btn', function() {
            performSearch();
        });
        
        $(document).on('keypress', '#pkb-search-input', function(e) {
            if (e.which === 13) {
                performSearch();
            }
        });
        
        // Filter changes
        $(document).on('change', '#pkb-filter-type, #pkb-filter-domain, #pkb-filter-status', function() {
            currentPage = 0;
            loadClaims();
        });
        
        // Pagination
        $(document).on('click', '#pkb-prev-page', function() {
            if (currentPage > 0) {
                currentPage--;
                loadClaims();
            }
        });
        
        $(document).on('click', '#pkb-next-page', function() {
            currentPage++;
            loadClaims();
        });
        
        // Tab changes - load data when switching tabs
        $(document).on('shown.bs.tab', '#pkb-tabs a[data-toggle="tab"]', function(e) {
            var target = $(e.target).attr('href');
            if (target === '#pkb-entities-pane') {
                loadEntities();
            } else if (target === '#pkb-tags-pane') {
                loadTags();
            } else if (target === '#pkb-conflicts-pane') {
                loadConflicts();
            }
        });
        
        // Memory proposal save button
        $(document).on('click', '#memory-proposal-save', function() {
            saveSelectedProposals();
        });
        
        console.log('PKBManager initialized');
    }
    
    // Initialize on document ready
    $(document).ready(init);
    
    // ===========================================================================
    // Public API
    // ===========================================================================
    
    return {
        // API functions
        listClaims: listClaims,
        addClaim: addClaim,
        editClaim: editClaim,
        deleteClaim: deleteClaim,
        searchClaims: searchClaims,
        listEntities: listEntities,
        listTags: listTags,
        listConflicts: listConflicts,
        resolveConflict: resolveConflict,
        proposeUpdates: proposeUpdates,
        executeUpdates: executeUpdates,
        
        // UI functions
        openPKBModal: openPKBModal,
        openAddClaimModal: openAddClaimModal,
        checkMemoryUpdates: checkMemoryUpdates,
        showMemoryProposalModal: showMemoryProposalModal,
        
        // Data loading
        loadClaims: loadClaims,
        loadEntities: loadEntities,
        loadTags: loadTags,
        loadConflicts: loadConflicts,
        
        // Utility
        showToast: showToast
    };
})();
