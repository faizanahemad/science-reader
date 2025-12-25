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
    
    // Pending memory attachments - claim IDs to include in next message
    var pendingMemoryAttachments = [];
    // Store claim details for display in pending indicator
    var pendingMemoryDetails = {};
    
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
    
    // ===========================================================================
    // Pinning Functions (Deliberate Memory Attachment)
    // ===========================================================================
    
    /**
     * Pin or unpin a claim for global context inclusion.
     * Pinned claims are always included in LLM context regardless of query.
     * @param {string} claimId - Claim ID to pin/unpin
     * @param {boolean} pin - True to pin, false to unpin
     * @returns {Promise} jQuery AJAX promise
     */
    function pinClaim(claimId, pin) {
        pin = (pin !== undefined) ? pin : true;
        return $.ajax({
            url: '/pkb/claims/' + claimId + '/pin',
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ pin: pin }),
            dataType: 'json'
        });
    }
    
    /**
     * Get all globally pinned claims.
     * @param {number} limit - Max results (default: 50)
     * @returns {Promise} jQuery AJAX promise
     */
    function getPinnedClaims(limit) {
        limit = limit || 50;
        return $.ajax({
            url: '/pkb/pinned?limit=' + limit,
            method: 'GET',
            dataType: 'json'
        });
    }
    
    /**
     * Check if a claim is pinned by parsing its meta_json.
     * @param {Object} claim - Claim object with meta_json field
     * @returns {boolean} True if pinned
     */
    function isClaimPinned(claim) {
        if (!claim || !claim.meta_json) return false;
        try {
            var meta = JSON.parse(claim.meta_json);
            return meta.pinned === true;
        } catch (e) {
            return false;
        }
    }
    
    /**
     * Toggle pin status of a claim and refresh UI.
     * @param {string} claimId - Claim ID
     * @param {boolean} currentlyPinned - Current pin status
     */
    function togglePinAndRefresh(claimId, currentlyPinned) {
        var newPinStatus = !currentlyPinned;
        
        pinClaim(claimId, newPinStatus)
            .done(function(response) {
                if (response.success) {
                    var msg = newPinStatus ? 
                        'Memory pinned - will always be included in context' : 
                        'Memory unpinned';
                    showToast(msg, 'success');
                    loadClaims();  // Refresh to show updated pin state
                } else {
                    showToast('Failed to update pin status', 'error');
                }
            })
            .fail(function(err) {
                console.error('Failed to toggle pin:', err);
                showToast('Failed to update pin status', 'error');
            });
    }
    
    // ===========================================================================
    // Conversation-Level Pinning Functions
    // ===========================================================================
    
    /**
     * Pin or unpin a claim to a specific conversation.
     * Conversation-pinned claims are included in context only for that conversation.
     * @param {string} conversationId - Conversation ID
     * @param {string} claimId - Claim ID to pin/unpin
     * @param {boolean} pin - True to pin, false to unpin
     * @returns {Promise} jQuery AJAX promise
     */
    function pinToConversation(conversationId, claimId, pin) {
        pin = (pin !== undefined) ? pin : true;
        return $.ajax({
            url: '/pkb/conversation/' + conversationId + '/pin',
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ 
                claim_id: claimId,
                pin: pin 
            }),
            dataType: 'json'
        });
    }
    
    /**
     * Get all claims pinned to a conversation.
     * @param {string} conversationId - Conversation ID
     * @returns {Promise} jQuery AJAX promise
     */
    function getConversationPinned(conversationId) {
        return $.ajax({
            url: '/pkb/conversation/' + conversationId + '/pinned',
            method: 'GET',
            dataType: 'json'
        });
    }
    
    /**
     * Clear all pinned claims for a conversation.
     * @param {string} conversationId - Conversation ID
     * @returns {Promise} jQuery AJAX promise
     */
    function clearConversationPinned(conversationId) {
        return $.ajax({
            url: '/pkb/conversation/' + conversationId + '/pinned',
            method: 'DELETE',
            dataType: 'json'
        });
    }
    
    /**
     * Pin a claim to the current conversation and show feedback.
     * @param {string} claimId - Claim ID to pin
     */
    function pinToCurrentConversation(claimId) {
        // Get current conversation ID from URL or ConversationManager
        var conversationId = null;
        if (typeof ConversationManager !== 'undefined' && ConversationManager.activeConversationId) {
            conversationId = ConversationManager.activeConversationId;
        } else {
            // Try to extract from URL
            var pathParts = window.location.pathname.split('/');
            if (pathParts.length > 2 && pathParts[1] === 'interface') {
                conversationId = pathParts[2].split('#')[0];
            }
        }
        
        if (!conversationId) {
            showToast('No active conversation found', 'error');
            return;
        }
        
        pinToConversation(conversationId, claimId, true)
            .done(function(response) {
                if (response.success) {
                    showToast('Memory pinned to this conversation', 'success');
                } else {
                    showToast('Failed to pin memory to conversation', 'error');
                }
            })
            .fail(function(err) {
                console.error('Failed to pin to conversation:', err);
                showToast('Failed to pin memory to conversation', 'error');
            });
    }
    
    // ===========================================================================
    // Pending Memory Attachments ("Use in next message" feature)
    // ===========================================================================
    
    /**
     * Add a claim to the pending memory attachments.
     * These will be included in the next message sent.
     * @param {string} claimId - Claim ID to attach
     */
    function addToNextMessage(claimId) {
        // Check if already added
        if (pendingMemoryAttachments.indexOf(claimId) >= 0) {
            showToast('Memory already queued for next message', 'info');
            return;
        }
        
        // Fetch claim details for display
        $.ajax({
            url: '/pkb/claims/' + claimId,
            method: 'GET',
            dataType: 'json'
        }).done(function(response) {
            if (response.claim) {
                pendingMemoryAttachments.push(claimId);
                pendingMemoryDetails[claimId] = {
                    statement: response.claim.statement,
                    claim_type: response.claim.claim_type
                };
                updatePendingAttachmentsIndicator();
                showToast('Memory added - will be included in next message', 'success');
            }
        }).fail(function(err) {
            console.error('Failed to fetch claim for attachment:', err);
            // Still add it even if we couldn't fetch details
            pendingMemoryAttachments.push(claimId);
            pendingMemoryDetails[claimId] = { statement: 'Memory ' + claimId.substring(0, 8), claim_type: 'unknown' };
            updatePendingAttachmentsIndicator();
            showToast('Memory added - will be included in next message', 'success');
        });
    }
    
    /**
     * Remove a claim from pending attachments.
     * @param {string} claimId - Claim ID to remove
     */
    function removeFromPending(claimId) {
        var idx = pendingMemoryAttachments.indexOf(claimId);
        if (idx >= 0) {
            pendingMemoryAttachments.splice(idx, 1);
            delete pendingMemoryDetails[claimId];
            updatePendingAttachmentsIndicator();
        }
    }
    
    /**
     * Clear all pending memory attachments.
     */
    function clearPendingAttachments() {
        pendingMemoryAttachments = [];
        pendingMemoryDetails = {};
        updatePendingAttachmentsIndicator();
    }
    
    /**
     * Get all pending memory attachment IDs.
     * @returns {Array<string>} Array of claim IDs
     */
    function getPendingAttachments() {
        return pendingMemoryAttachments.slice();  // Return copy
    }
    
    /**
     * Get pending attachment count.
     * @returns {number} Count of pending attachments
     */
    function getPendingCount() {
        return pendingMemoryAttachments.length;
    }
    
    /**
     * Update the pending attachments indicator in the UI.
     * Shows a visual indicator near the chat input when memories are queued.
     */
    function updatePendingAttachmentsIndicator() {
        var $indicator = $('#pending-memories-indicator');
        var $container = $('#pending-memories-container');
        
        // Create indicator if it doesn't exist
        if ($indicator.length === 0) {
            // Add indicator container near chat input
            var indicatorHtml = 
                '<div id="pending-memories-container" class="pending-memories-wrapper" style="display: none;">' +
                    '<div id="pending-memories-indicator" class="alert alert-info alert-dismissible py-1 px-2 mb-1" style="font-size: 0.85rem;">' +
                        '<strong><i class="bi bi-bookmark-star"></i> Memories attached:</strong> ' +
                        '<span id="pending-memories-list"></span> ' +
                        '<button type="button" class="btn btn-sm btn-link text-info p-0 ml-2" id="clear-pending-memories" title="Clear all">' +
                            '<i class="bi bi-x-circle"></i> Clear' +
                        '</button>' +
                    '</div>' +
                '</div>';
            
            // Try to insert before chat input area
            var $chatInput = $('#chat-input-container, #user-input, .chat-input-area').first();
            if ($chatInput.length) {
                $chatInput.before(indicatorHtml);
            } else {
                // Fallback: append to body and position
                $('body').append(indicatorHtml);
            }
            
            $indicator = $('#pending-memories-indicator');
            $container = $('#pending-memories-container');
            
            // Bind clear button
            $('#clear-pending-memories').on('click', function() {
                clearPendingAttachments();
            });
        }
        
        if (pendingMemoryAttachments.length === 0) {
            $container.hide();
            return;
        }
        
        // Build chips for each pending memory
        var chips = pendingMemoryAttachments.map(function(claimId) {
            var details = pendingMemoryDetails[claimId] || {};
            var shortStatement = (details.statement || '').substring(0, 40);
            if (details.statement && details.statement.length > 40) shortStatement += '...';
            
            return '<span class="badge badge-pill badge-primary mr-1" style="font-weight: normal;">' +
                escapeHtml(shortStatement) +
                ' <button type="button" class="btn btn-sm p-0 ml-1 text-white remove-pending-memory" data-claim-id="' + claimId + '" style="line-height: 1;">' +
                    '<i class="bi bi-x"></i>' +
                '</button>' +
            '</span>';
        });
        
        $('#pending-memories-list').html(chips.join(''));
        $container.show();
        
        // Bind remove buttons
        $('.remove-pending-memory').off('click').on('click', function(e) {
            e.preventDefault();
            e.stopPropagation();
            var claimId = $(this).data('claim-id');
            removeFromPending(claimId);
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
        
        // Check if claim is pinned
        var isPinned = isClaimPinned(claim);
        var pinBtnClass = isPinned ? 'btn-warning' : 'btn-outline-warning';
        var pinIcon = isPinned ? 'bi-pin-fill' : 'bi-pin';
        var pinTitle = isPinned ? 'Unpin (currently always included)' : 'Pin (always include in context)';
        var pinnedBadge = isPinned ? 
            '<span class="badge badge-warning ml-2"><i class="bi bi-pin-fill"></i> Pinned</span>' : '';
        
        return '<div class="list-group-item ' + statusClass + '" data-claim-id="' + claim.claim_id + '">' +
            '<div class="d-flex w-100 justify-content-between align-items-start">' +
                '<div class="flex-grow-1">' +
                    '<p class="mb-1">' + escapeHtml(claim.statement) + '</p>' +
                    '<small class="text-muted">' +
                        renderClaimTypeBadge(claim.claim_type) + ' ' +
                        '<span class="badge badge-outline-secondary">' + claim.context_domain + '</span>' +
                        contestedBadge +
                        pinnedBadge +
                    '</small>' +
                '</div>' +
                '<div class="btn-group btn-group-sm">' +
                    '<button class="btn ' + pinBtnClass + ' pkb-pin-claim" data-claim-id="' + claim.claim_id + '" data-pinned="' + isPinned + '" title="' + pinTitle + '">' +
                        '<i class="bi ' + pinIcon + '"></i>' +
                    '</button>' +
                    '<button class="btn btn-outline-info pkb-use-now-claim" data-claim-id="' + claim.claim_id + '" title="Use in next message">' +
                        '<i class="bi bi-chat-right-text"></i>' +
                    '</button>' +
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
        
        // Bind pin button handler
        $list.find('.pkb-pin-claim').on('click', function() {
            var claimId = $(this).data('claim-id');
            var isPinned = $(this).data('pinned') === true || $(this).data('pinned') === 'true';
            togglePinAndRefresh(claimId, isPinned);
        });
        
        // Bind "Use in next message" button handler
        $list.find('.pkb-use-now-claim').on('click', function() {
            var claimId = $(this).data('claim-id');
            addToNextMessage(claimId);
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
    // Bulk Add Functions
    // ===========================================================================
    
    var bulkRowCounter = 0;
    
    /**
     * Render a single bulk add row.
     * @param {number} index - Row index
     * @returns {string} HTML for the row
     */
    function renderBulkRow(index) {
        return '<div class="pkb-bulk-row card mb-2 p-2" data-index="' + index + '">' +
            '<div class="form-row align-items-start">' +
                '<div class="col-12 mb-2">' +
                    '<textarea class="form-control form-control-sm bulk-row-statement" rows="2" ' +
                        'placeholder="What do you want to remember?"></textarea>' +
                '</div>' +
                '<div class="col-4">' +
                    '<select class="form-control form-control-sm bulk-row-type">' +
                        '<option value="fact">Fact</option>' +
                        '<option value="preference" selected>Preference</option>' +
                        '<option value="decision">Decision</option>' +
                        '<option value="task">Task</option>' +
                        '<option value="reminder">Reminder</option>' +
                        '<option value="habit">Habit</option>' +
                        '<option value="memory">Memory</option>' +
                        '<option value="observation">Observation</option>' +
                    '</select>' +
                '</div>' +
                '<div class="col-4">' +
                    '<select class="form-control form-control-sm bulk-row-domain">' +
                        '<option value="personal" selected>Personal</option>' +
                        '<option value="health">Health</option>' +
                        '<option value="work">Work</option>' +
                        '<option value="relationships">Relationships</option>' +
                        '<option value="learning">Learning</option>' +
                        '<option value="life_ops">Life Ops</option>' +
                        '<option value="finance">Finance</option>' +
                    '</select>' +
                '</div>' +
                '<div class="col-3">' +
                    '<input type="text" class="form-control form-control-sm bulk-row-tags" ' +
                        'placeholder="Tags (comma sep.)">' +
                '</div>' +
                '<div class="col-1">' +
                    '<button class="btn btn-sm btn-outline-danger pkb-bulk-remove-row" ' +
                        'data-index="' + index + '" title="Remove">' +
                        '<i class="bi bi-x"></i>' +
                    '</button>' +
                '</div>' +
            '</div>' +
        '</div>';
    }
    
    /**
     * Add a new row to the bulk add interface.
     */
    function addBulkRow() {
        var rowHtml = renderBulkRow(bulkRowCounter);
        $('#pkb-bulk-rows-container').append(rowHtml);
        bulkRowCounter++;
        
        // Focus the new textarea
        $('#pkb-bulk-rows-container .pkb-bulk-row:last-child .bulk-row-statement').focus();
    }
    
    /**
     * Remove a bulk add row.
     * @param {number} index - Row index to remove
     */
    function removeBulkRow(index) {
        $('.pkb-bulk-row[data-index="' + index + '"]').remove();
    }
    
    /**
     * Clear all bulk add rows.
     */
    function clearBulkRows() {
        $('#pkb-bulk-rows-container').empty();
        bulkRowCounter = 0;
        
        // Add one empty row
        addBulkRow();
    }
    
    /**
     * Initialize bulk add tab when shown.
     */
    function initBulkAddTab() {
        if ($('#pkb-bulk-rows-container').children().length === 0) {
            addBulkRow();
        }
    }
    
    /**
     * Collect all bulk rows data.
     * @returns {Array} Array of claim objects
     */
    function collectBulkRows() {
        var claims = [];
        
        $('.pkb-bulk-row').each(function() {
            var statement = $(this).find('.bulk-row-statement').val().trim();
            if (statement) {
                var tagsStr = $(this).find('.bulk-row-tags').val().trim();
                var tags = tagsStr ? tagsStr.split(',').map(function(t) { return t.trim(); }).filter(Boolean) : [];
                
                claims.push({
                    statement: statement,
                    claim_type: $(this).find('.bulk-row-type').val(),
                    context_domain: $(this).find('.bulk-row-domain').val(),
                    tags: tags
                });
            }
        });
        
        return claims;
    }
    
    /**
     * Save all bulk claims to the server.
     */
    function saveBulkClaims() {
        var claims = collectBulkRows();
        
        if (claims.length === 0) {
            showToast('Please add at least one memory.', 'warning');
            return;
        }
        
        // Show progress
        $('#pkb-bulk-progress').show();
        $('#pkb-bulk-results').hide();
        $('#pkb-bulk-save-all').prop('disabled', true);
        $('#pkb-bulk-progress-bar').css('width', '0%');
        $('#pkb-bulk-progress-text').text('Saving 0 of ' + claims.length + '...');
        
        // Send to server
        $.ajax({
            url: '/pkb/claims/bulk',
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({
                claims: claims,
                auto_extract: false,
                stop_on_error: false
            }),
            dataType: 'json'
        })
        .done(function(response) {
            // Update progress
            $('#pkb-bulk-progress-bar').css('width', '100%');
            $('#pkb-bulk-progress-text').text('Complete!');
            
            // Show results
            setTimeout(function() {
                $('#pkb-bulk-progress').hide();
                $('#pkb-bulk-results').show();
                
                $('#pkb-bulk-success-count').text(response.added_count);
                
                if (response.failed_count > 0) {
                    $('#pkb-bulk-error-alert').show();
                    $('#pkb-bulk-error-count').text(response.failed_count);
                } else {
                    $('#pkb-bulk-error-alert').hide();
                }
                
                if (response.added_count > 0) {
                    showToast('Saved ' + response.added_count + ' memories!', 'success');
                    
                    // Clear successful rows and refresh claims list
                    clearBulkRows();
                    loadClaims();
                }
                
                $('#pkb-bulk-save-all').prop('disabled', false);
            }, 500);
        })
        .fail(function(err) {
            $('#pkb-bulk-progress').hide();
            $('#pkb-bulk-save-all').prop('disabled', false);
            
            var errorMsg = err.responseJSON ? err.responseJSON.error : 'An error occurred';
            showToast('Failed to save memories: ' + errorMsg, 'error');
        });
    }
    
    // ===========================================================================
    // Text Ingestion Functions
    // ===========================================================================
    
    var currentIngestPlanId = null;
    var currentIngestProposals = [];
    
    /**
     * Analyze text for memory ingestion.
     */
    function analyzeTextForIngestion() {
        var text = $('#pkb-import-text').val().trim();
        
        if (!text) {
            showToast('Please enter some text to analyze.', 'warning');
            return;
        }
        
        var defaultType = $('#pkb-import-default-type').val();
        var defaultDomain = $('#pkb-import-default-domain').val();
        var useLlm = $('#pkb-import-use-llm').is(':checked');
        
        // Show loading
        $('#pkb-import-loading').show();
        $('#pkb-import-error').hide();
        $('#pkb-import-analyze').prop('disabled', true);
        
        $.ajax({
            url: '/pkb/ingest_text',
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({
                text: text,
                default_claim_type: defaultType,
                default_domain: defaultDomain,
                use_llm: useLlm
            }),
            dataType: 'json'
        })
        .done(function(response) {
            $('#pkb-import-loading').hide();
            $('#pkb-import-analyze').prop('disabled', false);
            
            if (!response.has_proposals || response.proposals.length === 0) {
                showToast('No memories could be extracted from the text.', 'info');
                return;
            }
            
            // Store plan for execution
            currentIngestPlanId = response.plan_id;
            currentIngestProposals = response.proposals;
            
            // Show in approval modal
            showBulkProposalModal(response.proposals, 'text_ingest', response.plan_id, response.summary);
        })
        .fail(function(err) {
            $('#pkb-import-loading').hide();
            $('#pkb-import-analyze').prop('disabled', false);
            
            var errorMsg = err.responseJSON ? err.responseJSON.error : 'An error occurred';
            $('#pkb-import-error').text(errorMsg).show();
            showToast('Failed to analyze text: ' + errorMsg, 'error');
        });
    }
    
    // ===========================================================================
    // Enhanced Bulk Approval Modal Functions
    // ===========================================================================
    
    /**
     * Render a single proposal row with edit capability.
     * @param {Object} proposal - The proposal object
     * @param {number} index - Index in proposals array
     * @returns {string} HTML for the row
     */
    function renderProposalRow(proposal, index) {
        var actionBadge = '';
        var checked = 'checked';
        var existingInfo = '';
        
        if (proposal.action === 'add') {
            actionBadge = '<span class="badge badge-success"><i class="bi bi-plus-circle"></i> New</span>';
        } else if (proposal.action === 'edit') {
            actionBadge = '<span class="badge badge-warning"><i class="bi bi-pencil"></i> Update</span>';
            if (proposal.existing_statement) {
                existingInfo = '<div class="small text-muted mt-1">' +
                    '<strong>Existing:</strong> ' + escapeHtml(proposal.existing_statement) +
                '</div>';
            }
        } else if (proposal.action === 'skip') {
            actionBadge = '<span class="badge badge-secondary"><i class="bi bi-dash-circle"></i> Skip</span>';
            checked = '';
        }
        
        var similarityInfo = '';
        if (proposal.similarity_score !== undefined && proposal.similarity_score !== null) {
            var pct = Math.round(proposal.similarity_score * 100);
            similarityInfo = '<span class="badge badge-light ml-1">' + pct + '% similar</span>';
        }
        
        return '<div class="proposal-row card mb-2 p-2" data-index="' + index + '">' +
            '<div class="form-row">' +
                '<div class="col-auto d-flex align-items-center">' +
                    '<input type="checkbox" class="proposal-checkbox" ' + checked + ' data-index="' + index + '">' +
                '</div>' +
                '<div class="col">' +
                    '<div class="d-flex align-items-center mb-1">' +
                        actionBadge + similarityInfo +
                        '<small class="text-muted ml-2">' + escapeHtml(proposal.reason || '') + '</small>' +
                    '</div>' +
                    '<textarea class="form-control form-control-sm proposal-statement" rows="2">' + 
                        escapeHtml(proposal.statement) + '</textarea>' +
                    existingInfo +
                    '<div class="form-row mt-1">' +
                        '<div class="col-auto">' +
                            '<select class="form-control form-control-sm proposal-type">' +
                                '<option value="fact"' + (proposal.claim_type === 'fact' ? ' selected' : '') + '>Fact</option>' +
                                '<option value="preference"' + (proposal.claim_type === 'preference' ? ' selected' : '') + '>Preference</option>' +
                                '<option value="decision"' + (proposal.claim_type === 'decision' ? ' selected' : '') + '>Decision</option>' +
                                '<option value="task"' + (proposal.claim_type === 'task' ? ' selected' : '') + '>Task</option>' +
                                '<option value="reminder"' + (proposal.claim_type === 'reminder' ? ' selected' : '') + '>Reminder</option>' +
                                '<option value="habit"' + (proposal.claim_type === 'habit' ? ' selected' : '') + '>Habit</option>' +
                                '<option value="memory"' + (proposal.claim_type === 'memory' ? ' selected' : '') + '>Memory</option>' +
                                '<option value="observation"' + (proposal.claim_type === 'observation' ? ' selected' : '') + '>Observation</option>' +
                            '</select>' +
                        '</div>' +
                        '<div class="col-auto">' +
                            '<select class="form-control form-control-sm proposal-domain">' +
                                '<option value="personal"' + (proposal.context_domain === 'personal' ? ' selected' : '') + '>Personal</option>' +
                                '<option value="health"' + (proposal.context_domain === 'health' ? ' selected' : '') + '>Health</option>' +
                                '<option value="work"' + (proposal.context_domain === 'work' ? ' selected' : '') + '>Work</option>' +
                                '<option value="relationships"' + (proposal.context_domain === 'relationships' ? ' selected' : '') + '>Relationships</option>' +
                                '<option value="learning"' + (proposal.context_domain === 'learning' ? ' selected' : '') + '>Learning</option>' +
                                '<option value="life_ops"' + (proposal.context_domain === 'life_ops' ? ' selected' : '') + '>Life Ops</option>' +
                                '<option value="finance"' + (proposal.context_domain === 'finance' ? ' selected' : '') + '>Finance</option>' +
                            '</select>' +
                        '</div>' +
                    '</div>' +
                '</div>' +
            '</div>' +
        '</div>';
    }
    
    /**
     * Show the bulk proposal modal.
     * @param {Array} proposals - Array of proposal objects
     * @param {string} source - Source ('conversation' or 'text_ingest')
     * @param {string} planId - Plan ID for execution
     * @param {string} summary - Optional summary text
     */
    function showBulkProposalModal(proposals, source, planId, summary) {
        var $list = $('#memory-proposal-list');
        var addCount = 0, editCount = 0, skipCount = 0;
        
        // Render all proposals
        var html = '';
        proposals.forEach(function(proposal, index) {
            html += renderProposalRow(proposal, index);
            
            if (proposal.action === 'add') addCount++;
            else if (proposal.action === 'edit') editCount++;
            else if (proposal.action === 'skip') skipCount++;
        });
        
        $list.html(html);
        
        // Update counts
        $('#proposal-add-count').html('<i class="bi bi-plus-circle"></i> ' + addCount + ' new');
        $('#proposal-edit-count').html('<i class="bi bi-pencil"></i> ' + editCount + ' updates');
        $('#proposal-skip-count').html('<i class="bi bi-dash-circle"></i> ' + skipCount + ' skipped');
        
        // Set hidden fields
        $('#memory-proposal-plan-id').val(planId);
        $('#memory-proposal-source').val(source);
        
        // Update intro
        if (summary) {
            $('#memory-proposal-intro').text(summary);
        } else if (source === 'text_ingest') {
            $('#memory-proposal-intro').text('Review the memories extracted from your text:');
        } else {
            $('#memory-proposal-intro').text('Review the proposed memory updates:');
        }
        
        // Update selected count
        updateProposalSelectedCount();
        
        // Show modal
        $('#memory-proposal-modal').modal('show');
    }
    
    /**
     * Update the selected proposals count.
     */
    function updateProposalSelectedCount() {
        var count = $('.proposal-checkbox:checked').length;
        $('#proposal-selected-count').text(count);
        $('#proposal-save-count').text(count);
    }
    
    /**
     * Collect approved proposals with any edits.
     * @returns {Array} Array of approved proposal data
     */
    function collectApprovedProposals() {
        var approved = [];
        
        $('.proposal-row').each(function() {
            var $row = $(this);
            if ($row.find('.proposal-checkbox').is(':checked')) {
                approved.push({
                    index: parseInt($row.data('index'), 10),
                    statement: $row.find('.proposal-statement').val().trim(),
                    claim_type: $row.find('.proposal-type').val(),
                    context_domain: $row.find('.proposal-domain').val()
                });
            }
        });
        
        return approved;
    }
    
    /**
     * Save selected proposals (enhanced version).
     */
    function saveSelectedProposals() {
        var planId = $('#memory-proposal-plan-id').val();
        var source = $('#memory-proposal-source').val() || 'conversation';
        var approved = collectApprovedProposals();
        
        if (approved.length === 0) {
            $('#memory-proposal-modal').modal('hide');
            return;
        }
        
        // Determine which endpoint to use
        var endpoint = source === 'text_ingest' ? '/pkb/execute_ingest' : '/pkb/execute_updates';
        
        // Prepare request data
        var requestData = {
            plan_id: planId
        };
        
        if (source === 'text_ingest') {
            requestData.approved = approved;
        } else {
            // For conversation-based updates, use the simpler format
            requestData.approved_indices = approved.map(function(a) { return a.index; });
        }
        
        $.ajax({
            url: endpoint,
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify(requestData),
            dataType: 'json'
        })
        .done(function(response) {
            $('#memory-proposal-modal').modal('hide');
            
            var successCount = response.executed_count || response.added_count || 0;
            if (successCount > 0) {
                showToast('Saved ' + successCount + ' memories!', 'success');
                
                // Refresh claims list
                loadClaims();
                
                // Clear import text if this was text ingest
                if (source === 'text_ingest') {
                    $('#pkb-import-text').val('');
                }
            }
            
            if (response.failed_count > 0) {
                showToast(response.failed_count + ' memories failed to save.', 'warning');
            }
        })
        .fail(function(err) {
            console.error('Failed to save proposals:', err);
            var errorMsg = err.responseJSON ? err.responseJSON.error : 'An error occurred';
            showToast('Failed to save memories: ' + errorMsg, 'error');
        });
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
            } else if (target === '#pkb-bulk-pane') {
                initBulkAddTab();
            }
        });
        
        // Memory proposal save button
        $(document).on('click', '#memory-proposal-save', function() {
            saveSelectedProposals();
        });
        
        // Bulk Add tab handlers
        $(document).on('click', '#pkb-bulk-add-row', function() {
            addBulkRow();
        });
        
        $(document).on('click', '.pkb-bulk-remove-row', function() {
            var index = $(this).data('index');
            removeBulkRow(index);
        });
        
        $(document).on('click', '#pkb-bulk-clear-all', function() {
            clearBulkRows();
        });
        
        $(document).on('click', '#pkb-bulk-save-all', function() {
            saveBulkClaims();
        });
        
        // Text Import tab handlers
        $(document).on('click', '#pkb-import-analyze', function() {
            analyzeTextForIngestion();
        });
        
        // Proposal modal handlers
        $(document).on('click', '#proposal-select-all', function() {
            $('.proposal-checkbox').prop('checked', true);
            updateProposalSelectedCount();
        });
        
        $(document).on('click', '#proposal-deselect-all', function() {
            $('.proposal-checkbox').prop('checked', false);
            updateProposalSelectedCount();
        });
        
        $(document).on('change', '.proposal-checkbox', function() {
            updateProposalSelectedCount();
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
        
        // Global pinning functions (Deliberate Memory Attachment)
        pinClaim: pinClaim,
        getPinnedClaims: getPinnedClaims,
        isClaimPinned: isClaimPinned,
        togglePinAndRefresh: togglePinAndRefresh,
        
        // Conversation-level pinning
        pinToConversation: pinToConversation,
        getConversationPinned: getConversationPinned,
        clearConversationPinned: clearConversationPinned,
        pinToCurrentConversation: pinToCurrentConversation,
        
        // Pending attachments ("Use in next message")
        addToNextMessage: addToNextMessage,
        removeFromPending: removeFromPending,
        clearPendingAttachments: clearPendingAttachments,
        getPendingAttachments: getPendingAttachments,
        getPendingCount: getPendingCount,
        updatePendingAttachmentsIndicator: updatePendingAttachmentsIndicator,
        
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
        
        // Bulk Add functions
        addBulkRow: addBulkRow,
        removeBulkRow: removeBulkRow,
        clearBulkRows: clearBulkRows,
        saveBulkClaims: saveBulkClaims,
        
        // Text Ingestion functions
        analyzeTextForIngestion: analyzeTextForIngestion,
        
        // Enhanced Proposal Modal functions
        showBulkProposalModal: showBulkProposalModal,
        collectApprovedProposals: collectApprovedProposals,
        updateProposalSelectedCount: updateProposalSelectedCount,
        
        // Utility
        showToast: showToast
    };
})();
