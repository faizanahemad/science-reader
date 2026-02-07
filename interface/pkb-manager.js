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
    
    // When set, the next saveClaim() will link the new claim to this entity
    var _pendingEntityLink = null;
    
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
    /**
     * List or search claims via the unified GET /pkb/claims endpoint.
     *
     * When `query` is provided it performs a hybrid search with filters.
     * When absent it does a simple DB list with filters + pagination.
     *
     * @param {Object}  [filters]         - {claim_type, context_domain, status}
     * @param {number}  [limit]           - Max results
     * @param {number}  [offset]          - Pagination offset (list mode only)
     * @param {string}  [query]           - Free-text search query
     * @param {string}  [strategy]        - Search strategy (default: hybrid)
     * @returns {Promise} jQuery AJAX promise resolving to {claims: [...], count: N}
     */
    function listClaims(filters, limit, offset, query, strategy) {
        filters = filters || {};
        limit = limit || pageSize;
        offset = offset || 0;
        
        var queryParams = new URLSearchParams();
        if (filters.claim_type) queryParams.append('claim_type', filters.claim_type);
        if (filters.context_domain) queryParams.append('context_domain', filters.context_domain);
        if (filters.status) queryParams.append('status', filters.status);
        queryParams.append('limit', limit);
        queryParams.append('offset', offset);
        if (query) queryParams.append('query', query);
        if (strategy) queryParams.append('strategy', strategy);
        
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
        
        // Claim number badge (v0.5.1) — short numeric ID like #42
        var claimNumberBadge = '';
        if (claim.claim_number) {
            claimNumberBadge = '<span class="badge badge-dark text-monospace mr-1" title="Use @claim_' + claim.claim_number + ' in chat">#' + claim.claim_number + '</span>';
        }
        
        // Friendly ID badge (v0.5)
        var friendlyIdBadge = '';
        if (claim.friendly_id) {
            friendlyIdBadge = '<span class="badge badge-light text-monospace mr-1" title="Use @' + escapeHtml(claim.friendly_id) + ' in chat">@' + escapeHtml(claim.friendly_id) + '</span>';
        }
        
        return '<div class="list-group-item ' + statusClass + '" data-claim-id="' + claim.claim_id + '" data-claim-number="' + (claim.claim_number || '') + '" data-friendly-id="' + (claim.friendly_id || '') + '">' +
            '<div class="d-flex w-100 justify-content-between align-items-start">' +
                '<div class="flex-grow-1">' +
                    '<p class="mb-1">' + escapeHtml(claim.statement) + '</p>' +
                    '<small class="text-muted">' +
                        claimNumberBadge +
                        friendlyIdBadge +
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
        bindClaimCardActions($list, function() { loadClaims(); });
    }
    
    // ===========================================================================
    // Shared: Bind claim card action handlers on any container
    // ===========================================================================
    
    /**
     * Bind Pin / Use-in-next / Edit / Delete handlers on claim cards inside a
     * container.  Reusable across Claims tab, Entity expansion, Tag expansion,
     * and Context expansion.
     *
     * @param {jQuery} $container - The jQuery container holding .list-group-item
     *   cards rendered by renderClaimCard().
     * @param {Function} [refreshCallback] - Optional callback invoked after a
     *   delete so the caller can re-fetch the list.
     */
    function bindClaimCardActions($container, refreshCallback) {
        $container.find('.pkb-edit-claim').on('click', function() {
            openEditClaimModal($(this).data('claim-id'));
        });
        $container.find('.pkb-delete-claim').on('click', function() {
            var cid = $(this).data('claim-id');
            if (confirm('Are you sure you want to delete this memory?')) {
                deleteClaim(cid).done(function(response) {
                    if (response.success) {
                        showToast('Memory deleted.', 'success');
                        if (refreshCallback) refreshCallback();
                        else loadClaims();
                    } else {
                        showToast(response.error || 'Failed to delete memory.', 'error');
                    }
                }).fail(function() {
                    showToast('Failed to delete memory.', 'error');
                });
            }
        });
        $container.find('.pkb-pin-claim').on('click', function() {
            var cid = $(this).data('claim-id');
            var pinned = $(this).data('pinned') === true || $(this).data('pinned') === 'true';
            togglePinAndRefresh(cid, pinned);
        });
        $container.find('.pkb-use-now-claim').on('click', function() {
            addToNextMessage($(this).data('claim-id'));
        });
    }

    // ===========================================================================
    // Expandable Entity Cards (v0.5.1)
    // ===========================================================================
    
    /** Cache: entityId -> claims array (cleared when entities tab reloads). */
    var _entityClaimsCache = {};

    /**
     * Render an expandable entity card.
     *
     * Displays the entity name, type badge, an expand/collapse chevron and an
     * "Add Memory" button.  A hidden container below the header holds the
     * claim cards that are lazily loaded on first expand.
     *
     * @param {Object} entity - Entity object from the API.
     * @returns {string} HTML string.
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
        var eid = entity.entity_id;
        
        return '<div class="card mb-2 pkb-entity-card" data-entity-id="' + eid + '">' +
            '<div class="card-header p-2 d-flex justify-content-between align-items-center" style="cursor:pointer;" data-toggle-entity="' + eid + '">' +
                '<div>' +
                    '<i class="bi ' + icon + ' mr-2"></i>' +
                    '<strong>' + escapeHtml(entity.name) + '</strong> ' +
                    '<span class="badge badge-secondary">' + entity.entity_type + '</span>' +
                '</div>' +
                '<div>' +
                    '<button class="btn btn-sm btn-outline-success pkb-entity-add-memory mr-1" data-entity-id="' + eid + '" data-entity-name="' + escapeHtml(entity.name) + '" title="Add memory to this entity">' +
                        '<i class="bi bi-plus-lg"></i>' +
                    '</button>' +
                    '<i class="bi bi-chevron-down pkb-entity-chevron" data-entity-id="' + eid + '"></i>' +
                '</div>' +
            '</div>' +
            '<div class="collapse" id="entity-claims-' + eid + '">' +
                '<div class="card-body p-2 pkb-entity-claims-container" data-entity-id="' + eid + '">' +
                    '<div class="text-center text-muted py-2"><div class="spinner-border spinner-border-sm" role="status"></div> Loading...</div>' +
                '</div>' +
            '</div>' +
        '</div>';
    }
    
    /**
     * Toggle the expanded claims list under an entity card.
     * Lazily fetches claims on first expand and caches them.
     *
     * @param {string} entityId - UUID of the entity.
     */
    function toggleEntityClaims(entityId) {
        var $collapse = $('#entity-claims-' + entityId);
        var isOpen = $collapse.hasClass('show');
        
        // Toggle chevron direction
        var $chev = $('.pkb-entity-chevron[data-entity-id="' + entityId + '"]');
        
        if (isOpen) {
            $collapse.collapse('hide');
            $chev.removeClass('bi-chevron-up').addClass('bi-chevron-down');
            return;
        }
        
        $collapse.collapse('show');
        $chev.removeClass('bi-chevron-down').addClass('bi-chevron-up');
        
        // If already cached just render
        if (_entityClaimsCache[entityId]) {
            renderEntityClaimsList(entityId, _entityClaimsCache[entityId]);
            return;
        }
        
        // Fetch claims for this entity
        $.ajax({
            url: '/pkb/entities/' + entityId + '/claims',
            method: 'GET',
            dataType: 'json'
        }).done(function(resp) {
            var claims = resp.claims || [];
            _entityClaimsCache[entityId] = claims;
            renderEntityClaimsList(entityId, claims);
        }).fail(function() {
            var $c = $('.pkb-entity-claims-container[data-entity-id="' + entityId + '"]');
            $c.html('<div class="text-center text-muted py-2">Failed to load memories.</div>');
        });
    }
    
    /**
     * Render claim cards inside an expanded entity container and bind handlers.
     *
     * @param {string} entityId - UUID of the entity.
     * @param {Array} claims - Array of claim objects.
     */
    function renderEntityClaimsList(entityId, claims) {
        var $c = $('.pkb-entity-claims-container[data-entity-id="' + entityId + '"]');
        if (!claims || claims.length === 0) {
            $c.html('<div class="text-center text-muted py-2"><small>No memories linked to this entity.</small></div>');
            return;
        }
        var html = '<div class="list-group list-group-flush">' + claims.map(renderClaimCard).join('') + '</div>';
        $c.html(html);
        bindClaimCardActions($c, function() {
            // After delete, invalidate cache and re-fetch
            delete _entityClaimsCache[entityId];
            toggleEntityClaims(entityId); // collapse
            toggleEntityClaims(entityId); // re-expand with fresh data
        });
    }
    
    /**
     * Render the entities list with expandable cards.
     * @param {Array} entities - Array of entity objects
     */
    function renderEntitiesList(entities) {
        var $list = $('#pkb-entities-list');
        _entityClaimsCache = {}; // clear cache on full reload
        
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
        
        // Bind expand/collapse on header click
        $list.find('[data-toggle-entity]').on('click', function(e) {
            // Don't toggle when "Add Memory" button is clicked
            if ($(e.target).closest('.pkb-entity-add-memory').length) return;
            toggleEntityClaims($(this).data('toggle-entity'));
        });
        
        // Bind "Add Memory" button
        $list.find('.pkb-entity-add-memory').on('click', function(e) {
            e.stopPropagation();
            var eid = $(this).data('entity-id');
            var eName = $(this).data('entity-name');
            // Open add modal; after save we'll link the new claim to this entity
            _pendingEntityLink = { entityId: eid, entityName: eName };
            openAddClaimModal();
        });
    }

    // ===========================================================================
    // Expandable Tag Cards (v0.5.1)
    // ===========================================================================
    
    /** Cache: tagId -> claims array */
    var _tagClaimsCache = {};
    
    /**
     * Render an expandable tag card.
     *
     * @param {Object} tag - Tag object from the API.
     * @returns {string} HTML string.
     */
    function renderTagCard(tag) {
        var tid = tag.tag_id;
        return '<div class="card mb-2 pkb-tag-card" data-tag-id="' + tid + '">' +
            '<div class="card-header p-2 d-flex justify-content-between align-items-center" style="cursor:pointer;" data-toggle-tag="' + tid + '">' +
                '<div>' +
                    '<i class="bi bi-tag mr-2"></i>' +
                    '<strong>' + escapeHtml(tag.name) + '</strong>' +
                '</div>' +
                '<i class="bi bi-chevron-down pkb-tag-chevron" data-tag-id="' + tid + '"></i>' +
            '</div>' +
            '<div class="collapse" id="tag-claims-' + tid + '">' +
                '<div class="card-body p-2 pkb-tag-claims-container" data-tag-id="' + tid + '">' +
                    '<div class="text-center text-muted py-2"><div class="spinner-border spinner-border-sm" role="status"></div> Loading...</div>' +
                '</div>' +
            '</div>' +
        '</div>';
    }
    
    /**
     * Toggle expanded claims list under a tag card.
     *
     * @param {string} tagId - UUID of the tag.
     */
    function toggleTagClaims(tagId) {
        var $collapse = $('#tag-claims-' + tagId);
        var isOpen = $collapse.hasClass('show');
        var $chev = $('.pkb-tag-chevron[data-tag-id="' + tagId + '"]');
        
        if (isOpen) {
            $collapse.collapse('hide');
            $chev.removeClass('bi-chevron-up').addClass('bi-chevron-down');
            return;
        }
        
        $collapse.collapse('show');
        $chev.removeClass('bi-chevron-down').addClass('bi-chevron-up');
        
        if (_tagClaimsCache[tagId]) {
            renderTagClaimsList(tagId, _tagClaimsCache[tagId]);
            return;
        }
        
        $.ajax({
            url: '/pkb/tags/' + tagId + '/claims',
            method: 'GET',
            dataType: 'json'
        }).done(function(resp) {
            var claims = resp.claims || [];
            _tagClaimsCache[tagId] = claims;
            renderTagClaimsList(tagId, claims);
        }).fail(function() {
            var $c = $('.pkb-tag-claims-container[data-tag-id="' + tagId + '"]');
            $c.html('<div class="text-center text-muted py-2">Failed to load memories.</div>');
        });
    }
    
    /**
     * Render claim cards inside an expanded tag container and bind handlers.
     *
     * @param {string} tagId - UUID of the tag.
     * @param {Array} claims - Array of claim objects.
     */
    function renderTagClaimsList(tagId, claims) {
        var $c = $('.pkb-tag-claims-container[data-tag-id="' + tagId + '"]');
        if (!claims || claims.length === 0) {
            $c.html('<div class="text-center text-muted py-2"><small>No memories with this tag.</small></div>');
            return;
        }
        var html = '<div class="list-group list-group-flush">' + claims.map(renderClaimCard).join('') + '</div>';
        $c.html(html);
        bindClaimCardActions($c, function() {
            delete _tagClaimsCache[tagId];
            toggleTagClaims(tagId);
            toggleTagClaims(tagId);
        });
    }
    
    /**
     * Render the tags list with expandable cards.
     * @param {Array} tags - Array of tag objects
     */
    function renderTagsList(tags) {
        var $list = $('#pkb-tags-list');
        _tagClaimsCache = {};
        
        if (!tags || tags.length === 0) {
            $list.html(
                '<div class="text-center text-muted py-4">' +
                    '<i class="bi bi-tag" style="font-size: 2rem;"></i>' +
                    '<p>No tags found.</p>' +
                '</div>'
            );
            return;
        }
        
        var html = tags.map(renderTagCard).join('');
        $list.html(html);
        
        $list.find('[data-toggle-tag]').on('click', function() {
            toggleTagClaims($(this).data('toggle-tag'));
        });
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
     * Populate the contexts multi-select dropdown in the claim edit modal.
     * Fetches all contexts, renders as <option> elements, and optionally
     * pre-selects the given context IDs.
     *
     * @param {Array} [selectedIds] - Context IDs to pre-select.
     */
    function populateContextsDropdown(selectedIds) {
        var $sel = $('#pkb-claim-contexts');
        $sel.empty();
        listContexts().done(function(resp) {
            if (resp.success && resp.contexts && resp.contexts.length > 0) {
                resp.contexts.forEach(function(ctx) {
                    var selected = selectedIds && selectedIds.indexOf(ctx.context_id) !== -1;
                    $sel.append('<option value="' + ctx.context_id + '"' + (selected ? ' selected' : '') + '>' +
                        escapeHtml(ctx.name) + (ctx.friendly_id ? ' (@' + ctx.friendly_id + ')' : '') +
                    '</option>');
                });
            }
        });
    }
    
    /**
     * Populate the Type multi-select dropdown from /pkb/types.
     *
     * @param {Array} [selectedTypes] - Type names to pre-select (e.g. ['fact','preference']).
     */
    function populateTypesDropdown(selectedTypes) {
        var $sel = $('#pkb-claim-type');
        $sel.empty();
        $.ajax({ url: '/pkb/types', method: 'GET', dataType: 'json' }).done(function(resp) {
            var types = resp.types || [];
            types.forEach(function(t) {
                var selected = selectedTypes && selectedTypes.indexOf(t.type_name) !== -1;
                $sel.append('<option value="' + escapeHtml(t.type_name) + '"' + (selected ? ' selected' : '') + '>' +
                    escapeHtml(t.display_name || t.type_name) + '</option>');
            });
            // If nothing was selected and there's a default, select it
            if ((!selectedTypes || selectedTypes.length === 0) && $sel.find('option[value="preference"]').length) {
                $sel.val(['preference']);
            }
        }).fail(function() {
            // Fallback: populate with hardcoded defaults
            var defaults = ['fact','preference','decision','task','reminder','habit','memory','observation'];
            defaults.forEach(function(d) {
                var selected = selectedTypes && selectedTypes.indexOf(d) !== -1;
                $sel.append('<option value="' + d + '"' + (selected ? ' selected' : '') + '>' + d.charAt(0).toUpperCase() + d.slice(1) + '</option>');
            });
        });
    }
    
    /**
     * Populate the Domain multi-select dropdown from /pkb/domains.
     *
     * @param {Array} [selectedDomains] - Domain names to pre-select.
     */
    function populateDomainsDropdown(selectedDomains) {
        var $sel = $('#pkb-claim-domain');
        $sel.empty();
        $.ajax({ url: '/pkb/domains', method: 'GET', dataType: 'json' }).done(function(resp) {
            var domains = resp.domains || [];
            domains.forEach(function(d) {
                var selected = selectedDomains && selectedDomains.indexOf(d.domain_name) !== -1;
                $sel.append('<option value="' + escapeHtml(d.domain_name) + '"' + (selected ? ' selected' : '') + '>' +
                    escapeHtml(d.display_name || d.domain_name) + '</option>');
            });
            if ((!selectedDomains || selectedDomains.length === 0) && $sel.find('option[value="personal"]').length) {
                $sel.val(['personal']);
            }
        }).fail(function() {
            var defaults = ['personal','health','work','relationships','learning','life_ops','finance'];
            defaults.forEach(function(d) {
                var selected = selectedDomains && selectedDomains.indexOf(d) !== -1;
                $sel.append('<option value="' + d + '"' + (selected ? ' selected' : '') + '>' + d.replace('_', ' ').replace(/\b\w/g, function(l) { return l.toUpperCase(); }) + '</option>');
            });
        });
    }
    
    /**
     * Open the add claim modal.
     */
    function openAddClaimModal() {
        $('#pkb-claim-edit-id').val('');
        $('#pkb-claim-statement').val('');
        $('#pkb-claim-friendly-id').val('');
        populateTypesDropdown(['preference']);
        populateDomainsDropdown(['personal']);
        $('#pkb-claim-tags').val('');
        $('#pkb-claim-questions').val('');
        $('#pkb-claim-edit-title').text('Add Memory');
        populateContextsDropdown([]); // No pre-selection for new claim
        $('#pkb-claim-edit-modal').modal('show');
    }
    
    /**
     * Open the edit claim modal.
     * @param {string} claimId - Claim ID to edit
     */
    function openEditClaimModal(claimId) {
        // Fetch the claim and its contexts in parallel
        $.ajax({
            url: '/pkb/claims/' + claimId,
            method: 'GET',
            dataType: 'json'
        }).done(function(response) {
            var claim = response.claim;
            $('#pkb-claim-edit-id').val(claim.claim_id);
            $('#pkb-claim-statement').val(claim.statement);
            $('#pkb-claim-friendly-id').val(claim.friendly_id || '');
            $('#pkb-claim-tags').val(''); // Tags would need separate fetch
            $('#pkb-claim-edit-title').text('Edit Memory');
            
            // Populate possible questions (JSON array -> newline-separated text)
            var questionsText = '';
            if (claim.possible_questions) {
                try {
                    var pqArr = JSON.parse(claim.possible_questions);
                    if (Array.isArray(pqArr)) {
                        questionsText = pqArr.join('\n');
                    }
                } catch(e) {
                    questionsText = claim.possible_questions;
                }
            }
            $('#pkb-claim-questions').val(questionsText);
            
            // Determine selected types and domains
            // claim_types is a JSON string like '["preference","fact"]', or null
            var selectedTypes;
            try {
                selectedTypes = claim.claim_types ? JSON.parse(claim.claim_types) : [claim.claim_type];
            } catch(e) {
                selectedTypes = [claim.claim_type];
            }
            var selectedDomains;
            try {
                selectedDomains = claim.context_domains ? JSON.parse(claim.context_domains) : [claim.context_domain];
            } catch(e) {
                selectedDomains = [claim.context_domain];
            }
            
            populateTypesDropdown(selectedTypes);
            populateDomainsDropdown(selectedDomains);
            
            // Fetch contexts for this claim and pre-select them
            $.ajax({
                url: '/pkb/claims/' + claimId + '/contexts',
                method: 'GET',
                dataType: 'json'
            }).done(function(ctxResp) {
                var selectedIds = (ctxResp.contexts || []).map(function(c) { return c.context_id; });
                populateContextsDropdown(selectedIds);
            }).fail(function() {
                populateContextsDropdown([]);
            });
            
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
        var friendlyId = $('#pkb-claim-friendly-id').val().trim();
        var selectedTypes = $('#pkb-claim-type').val() || [];     // multi-select array
        var selectedDomains = $('#pkb-claim-domain').val() || []; // multi-select array
        var tagsStr = $('#pkb-claim-tags').val().trim();
        var selectedContextIds = $('#pkb-claim-contexts').val() || [];
        // Parse possible questions (newline-separated -> JSON array)
        var questionsRaw = $('#pkb-claim-questions').val().trim();
        var possibleQuestionsJson = null;
        if (questionsRaw) {
            var qArr = questionsRaw.split('\n').map(function(q) { return q.trim(); }).filter(function(q) { return q.length > 0; });
            if (qArr.length > 0) possibleQuestionsJson = JSON.stringify(qArr);
        }
        
        if (!statement) {
            showToast('Please enter something to remember.', 'warning');
            return;
        }
        
        // Primary type/domain = first selected; arrays sent as JSON
        var claimType = selectedTypes.length > 0 ? selectedTypes[0] : 'fact';
        var contextDomain = selectedDomains.length > 0 ? selectedDomains[0] : 'personal';
        var claimTypesJson = selectedTypes.length > 1 ? JSON.stringify(selectedTypes) : null;
        var contextDomainsJson = selectedDomains.length > 1 ? JSON.stringify(selectedDomains) : null;
        
        var tags = tagsStr ? tagsStr.split(',').map(function(t) { return t.trim(); }) : [];
        
        var promise;
        if (claimId) {
            // Edit
            var patch = {
                statement: statement,
                claim_type: claimType,
                context_domain: contextDomain
            };
            if (friendlyId) patch.friendly_id = friendlyId;
            if (claimTypesJson) patch.claim_types = claimTypesJson;
            if (contextDomainsJson) patch.context_domains = contextDomainsJson;
            if (possibleQuestionsJson) patch.possible_questions = possibleQuestionsJson;
            promise = editClaim(claimId, patch);
        } else {
            // Add
            var addData = {
                statement: statement,
                claim_type: claimType,
                context_domain: contextDomain,
                tags: tags,
                auto_extract: false
            };
            if (friendlyId) addData.friendly_id = friendlyId;
            if (claimTypesJson) addData.claim_types = claimTypesJson;
            if (contextDomainsJson) addData.context_domains = contextDomainsJson;
            if (possibleQuestionsJson) addData.possible_questions = possibleQuestionsJson;
            promise = addClaim(addData);
        }
        
        promise.done(function(response) {
            if (response.success || response.claim) {
                $('#pkb-claim-edit-modal').modal('hide');
                
                var savedClaimId = (response.claim && response.claim.claim_id) || claimId;
                
                // Chain of post-save actions (contexts, entity link)
                var postSaveChain = $.Deferred().resolve().promise();
                
                // Save context assignments if we have a claim ID
                if (savedClaimId && selectedContextIds) {
                    postSaveChain = postSaveChain.then(function() {
                        return $.ajax({
                            url: '/pkb/claims/' + savedClaimId + '/contexts',
                            method: 'PUT',
                            contentType: 'application/json',
                            data: JSON.stringify({ context_ids: selectedContextIds }),
                            dataType: 'json'
                        });
                    });
                }
                
                // If we have a pending entity link, add it
                if (_pendingEntityLink && savedClaimId) {
                    postSaveChain = postSaveChain.then(function() {
                        return linkEntityToClaim(savedClaimId, _pendingEntityLink.entityId, 'mentioned');
                    });
                }
                
                postSaveChain.always(function() {
                    var msg = 'Memory saved!';
                    if (_pendingEntityLink) {
                        msg = 'Memory saved and linked to ' + _pendingEntityLink.entityName + '!';
                        delete _entityClaimsCache[_pendingEntityLink.entityId];
                    }
                    _pendingEntityLink = null;
                    loadClaims();
                    showToast(msg, 'success');
                });
            } else {
                showToast(response.error || 'Failed to save memory.', 'error');
            }
        }).fail(function(err) {
            console.error('Failed to save claim:', err);
            _pendingEntityLink = null;
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
     * Load claims with current filters and optional search query.
     *
     * Reads the search input, filter dropdowns, and pagination state,
     * then calls the unified GET /pkb/claims endpoint (which handles
     * both list and search modes).
     */
    function loadClaims() {
        var query = $('#pkb-search-input').val() ? $('#pkb-search-input').val().trim() : '';
        
        // Collect filter values (multi-select returns array)
        var filterType = $('#pkb-filter-type').val();
        var filterDomain = $('#pkb-filter-domain').val();
        var filterStatus = $('#pkb-filter-status').val();
        
        var filters = {};
        // For multi-select, take first non-empty value
        if (filterType) {
            if (Array.isArray(filterType)) {
                filterType = filterType.filter(function(v) { return v; });
                if (filterType.length > 0) filters.claim_type = filterType[0];
            } else if (filterType) {
                filters.claim_type = filterType;
            }
        }
        if (filterDomain) {
            if (Array.isArray(filterDomain)) {
                filterDomain = filterDomain.filter(function(v) { return v; });
                if (filterDomain.length > 0) filters.context_domain = filterDomain[0];
            } else if (filterDomain) {
                filters.context_domain = filterDomain;
            }
        }
        filters.status = filterStatus || 'active';
        
        var limit = query ? 30 : pageSize;
        var offset = query ? 0 : currentPage * pageSize;
        
        listClaims(filters, limit, offset, query || undefined)
            .done(function(response) {
                renderClaimsList(response.claims);
                var label = query ? (response.count + ' results') : (response.count + ' claims');
                $('#pkb-claims-count').text(label);
                
                // Update pagination (disable when searching since search returns all at once)
                $('#pkb-prev-page').prop('disabled', currentPage === 0 || !!query);
                $('#pkb-next-page').prop('disabled', response.count < pageSize || !!query);
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
                // Also populate entity filter dropdown (v0.5)
                var $filter = $('#pkb-filter-entity');
                var currentVal = $filter.val();
                $filter.find('option:not(:first)').remove();
                if (response.entities) {
                    response.entities.forEach(function(entity) {
                        $filter.append('<option value="' + entity.entity_id + '">' + 
                            escapeHtml(entity.name) + ' (' + entity.entity_type + ')</option>');
                    });
                }
                if (currentVal) $filter.val(currentVal);
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
                // Also populate tag filter dropdown (v0.5)
                var $filter = $('#pkb-filter-tag');
                var currentVal = $filter.val();
                $filter.find('option:not(:first)').remove();
                if (response.tags) {
                    response.tags.forEach(function(tag) {
                        $filter.append('<option value="' + tag.tag_id + '">' + 
                            escapeHtml(tag.name) + '</option>');
                    });
                }
                if (currentVal) $filter.val(currentVal);
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
     * Perform a search — just delegates to loadClaims() which now reads
     * the search input and all filter dropdowns in one unified call.
     */
    function performSearch() {
        currentPage = 0;
        loadClaims();
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
        
        // Entity add button (v0.5)
        $('#pkb-add-entity-btn').on('click', function() {
            var name = $('#pkb-new-entity-name').val().trim();
            var entityType = $('#pkb-new-entity-type').val();
            if (!name) {
                showToast('Please enter an entity name', 'warning');
                return;
            }
            createEntity({ name: name, entity_type: entityType }).done(function(resp) {
                if (resp.success) {
                    showToast('Entity "' + name + '" created!', 'success');
                    $('#pkb-new-entity-name').val('');
                    loadEntities();
                } else {
                    showToast(resp.error || 'Failed to create entity', 'error');
                }
            }).fail(function() {
                showToast('Failed to create entity', 'error');
            });
        });
        
        // Context create button (v0.5)
        $('#pkb-create-context-btn').on('click', function() {
            var name = $('#pkb-new-context-name').val().trim();
            var friendlyId = $('#pkb-new-context-friendly-id').val().trim();
            var description = $('#pkb-new-context-description').val().trim();
            if (!name) {
                showToast('Please enter a context name', 'warning');
                return;
            }
            var data = { name: name };
            if (friendlyId) data.friendly_id = friendlyId;
            if (description) data.description = description;
            createContext(data).done(function(resp) {
                if (resp.success) {
                    showToast('Context "' + name + '" created!', 'success');
                    $('#pkb-new-context-name').val('');
                    $('#pkb-new-context-friendly-id').val('');
                    $('#pkb-new-context-description').val('');
                    loadContextsTab();
                } else {
                    showToast(resp.error || 'Failed to create context', 'error');
                }
            }).fail(function() {
                showToast('Failed to create context', 'error');
            });
        });
        
        // Load contexts when contexts tab is shown
        $('a[data-toggle="tab"]').on('shown.bs.tab', function(e) {
            if ($(e.target).attr('href') === '#pkb-contexts-pane') {
                loadContextsTab();
            }
        });
        
        // Filter change handlers (v0.5) - reload claims when filters change
        $('#pkb-filter-entity, #pkb-filter-tag, #pkb-sort-by').on('change', function() {
            loadClaims();
        });
        
        // Add New Type button (v0.5.1)
        $(document).on('click', '#pkb-add-new-type', function() {
            var newType = $('#pkb-new-type-input').val().trim().toLowerCase().replace(/\s+/g, '_');
            if (!newType) {
                showToast('Please enter a type name', 'warning');
                return;
            }
            $.ajax({
                url: '/pkb/types',
                method: 'POST',
                contentType: 'application/json',
                data: JSON.stringify({ type_name: newType }),
                dataType: 'json'
            }).done(function(resp) {
                if (resp.success) {
                    var display = resp.type.display_name || newType;
                    $('#pkb-claim-type').append('<option value="' + escapeHtml(newType) + '" selected>' + escapeHtml(display) + '</option>');
                    $('#pkb-new-type-input').val('');
                    showToast('Type "' + display + '" added!', 'success');
                }
            }).fail(function() {
                showToast('Failed to add type', 'error');
            });
        });
        
        // Add New Domain button (v0.5.1)
        $(document).on('click', '#pkb-add-new-domain', function() {
            var newDomain = $('#pkb-new-domain-input').val().trim().toLowerCase().replace(/\s+/g, '_');
            if (!newDomain) {
                showToast('Please enter a domain name', 'warning');
                return;
            }
            $.ajax({
                url: '/pkb/domains',
                method: 'POST',
                contentType: 'application/json',
                data: JSON.stringify({ domain_name: newDomain }),
                dataType: 'json'
            }).done(function(resp) {
                if (resp.success) {
                    var display = resp.domain.display_name || newDomain;
                    $('#pkb-claim-domain').append('<option value="' + escapeHtml(newDomain) + '" selected>' + escapeHtml(display) + '</option>');
                    $('#pkb-new-domain-input').val('');
                    showToast('Domain "' + display + '" added!', 'success');
                }
            }).fail(function() {
                showToast('Failed to add domain', 'error');
            });
        });
        
        console.log('PKBManager initialized (v0.5.1 with expandable entities/tags, context linking, dynamic types/domains)');
    }
    
    /** Cache: contextId -> claims array */
    var _contextClaimsCache = {};
    
    /**
     * Load and render contexts in the contexts tab with expandable claim lists.
     */
    function loadContextsTab() {
        _contextClaimsCache = {};
        listContexts().done(function(response) {
            var $list = $('#pkb-contexts-list');
            if (!response.success || !response.contexts || response.contexts.length === 0) {
                $list.html(
                    '<div class="text-center text-muted py-4">' +
                        '<i class="bi bi-folder" style="font-size: 2rem;"></i>' +
                        '<p>No contexts yet. Create one to group your memories!</p>' +
                    '</div>'
                );
                return;
            }
            
            var html = '';
            response.contexts.forEach(function(ctx) {
                var cid = ctx.context_id;
                html += '<div class="card mb-2 pkb-context-card" data-context-id="' + cid + '">' +
                    '<div class="card-header p-2 d-flex justify-content-between align-items-center" style="cursor:pointer;" data-toggle-context="' + cid + '">' +
                        '<div>' +
                            '<i class="bi bi-folder mr-2"></i>' +
                            '<strong>' + escapeHtml(ctx.name) + '</strong>' +
                            ' <span class="badge badge-light text-monospace">@' + escapeHtml(ctx.friendly_id || '') + '</span>' +
                            (ctx.description ? '<br><small class="text-muted">' + escapeHtml(ctx.description) + '</small>' : '') +
                            (ctx.parent_context_id ? '<br><small class="text-muted"><i class="bi bi-arrow-return-right"></i> Sub-context</small>' : '') +
                        '</div>' +
                        '<div class="d-flex align-items-center">' +
                            '<span class="badge badge-primary badge-pill mr-2">' + (ctx.claim_count || 0) + ' memories</span>' +
                            '<button class="btn btn-sm btn-outline-danger pkb-delete-context" data-context-id="' + cid + '" title="Delete context">' +
                                '<i class="bi bi-trash"></i>' +
                            '</button>' +
                            '<i class="bi bi-chevron-down pkb-context-chevron ml-2" data-context-id="' + cid + '"></i>' +
                        '</div>' +
                    '</div>' +
                    '<div class="collapse" id="context-claims-' + cid + '">' +
                        '<div class="card-body p-2 pkb-context-claims-container" data-context-id="' + cid + '">' +
                            '<div class="text-center text-muted py-2"><div class="spinner-border spinner-border-sm" role="status"></div> Loading...</div>' +
                        '</div>' +
                    '</div>' +
                '</div>';
            });
            $list.html(html);
            
            // Bind expand/collapse on header click
            $list.find('[data-toggle-context]').on('click', function(e) {
                if ($(e.target).closest('.pkb-delete-context').length) return;
                toggleContextClaims($(this).data('toggle-context'));
            });
            
            // Bind delete handlers
            $list.find('.pkb-delete-context').on('click', function(e) {
                e.stopPropagation();
                var contextId = $(this).data('context-id');
                if (confirm('Delete this context? (Memories inside will not be deleted)')) {
                    deleteContext(contextId).done(function(resp) {
                        if (resp.success) {
                            showToast('Context deleted', 'success');
                            loadContextsTab();
                        }
                    });
                }
            });
        });
    }
    
    /**
     * Toggle the expanded claims list under a context card.
     * When expanded, shows linked claims AND a search panel to add more.
     *
     * @param {string} contextId - UUID of the context.
     */
    function toggleContextClaims(contextId) {
        var $collapse = $('#context-claims-' + contextId);
        var isOpen = $collapse.hasClass('show');
        var $chev = $('.pkb-context-chevron[data-context-id="' + contextId + '"]');
        
        if (isOpen) {
            $collapse.collapse('hide');
            $chev.removeClass('bi-chevron-up').addClass('bi-chevron-down');
            return;
        }
        
        $collapse.collapse('show');
        $chev.removeClass('bi-chevron-down').addClass('bi-chevron-up');
        
        loadContextClaimsPanel(contextId);
    }
    
    /**
     * Load and render the full context claims panel: linked claims + search-to-add.
     *
     * @param {string} contextId - UUID of the context.
     */
    function loadContextClaimsPanel(contextId) {
        var $c = $('.pkb-context-claims-container[data-context-id="' + contextId + '"]');
        $c.html('<div class="text-center text-muted py-2"><div class="spinner-border spinner-border-sm" role="status"></div> Loading...</div>');
        
        // Fetch context details (which includes claims)
        $.ajax({
            url: '/pkb/contexts/' + contextId,
            method: 'GET',
            dataType: 'json'
        }).done(function(resp) {
            // Claims are nested inside resp.context.claims (not resp.claims)
            var ctx = resp.context || resp;
            var linkedClaims = ctx.claims || [];
            var linkedIds = {};
            linkedClaims.forEach(function(c) { linkedIds[c.claim_id] = true; });
            
            // Build the panel: linked claims section + search-to-add section
            var html = '';
            
            // --- Linked claims ---
            html += '<div class="mb-2"><strong><i class="bi bi-link-45deg"></i> Linked Memories (' + linkedClaims.length + ')</strong></div>';
            if (linkedClaims.length > 0) {
                html += '<div class="list-group list-group-flush mb-3 pkb-ctx-linked-claims">';
                linkedClaims.forEach(function(claim) {
                    html += renderContextLinkedClaimRow(claim, contextId);
                });
                html += '</div>';
            } else {
                html += '<div class="text-center text-muted py-2 mb-3"><small>No memories linked yet.</small></div>';
            }
            
            // --- Search-to-add section ---
            html += '<div class="border-top pt-2">';
            html += '<strong><i class="bi bi-plus-circle"></i> Add Memories</strong>';
            // Search bar
            html += '<div class="input-group input-group-sm mt-1 mb-1">';
            html += '<input type="text" class="form-control pkb-ctx-search-input" data-context-id="' + contextId + '" placeholder="Search by text, #number, @friendly_id...">';
            html += '<div class="input-group-append">';
            html += '<button class="btn btn-outline-primary pkb-ctx-search-btn" data-context-id="' + contextId + '" type="button"><i class="bi bi-search"></i></button>';
            html += '</div></div>';
            // Filter row: Type, Domain
            html += '<div class="form-row mb-2">';
            html += '<div class="col">';
            html += '<select class="form-control form-control-sm pkb-ctx-filter-type" data-context-id="' + contextId + '">';
            html += '<option value="">All Types</option>';
            html += '<option value="fact">Fact</option><option value="preference">Preference</option>';
            html += '<option value="decision">Decision</option><option value="task">Task</option>';
            html += '<option value="reminder">Reminder</option><option value="habit">Habit</option>';
            html += '<option value="memory">Memory</option><option value="observation">Observation</option>';
            html += '</select></div>';
            html += '<div class="col">';
            html += '<select class="form-control form-control-sm pkb-ctx-filter-domain" data-context-id="' + contextId + '">';
            html += '<option value="">All Domains</option>';
            html += '<option value="personal">Personal</option><option value="health">Health</option>';
            html += '<option value="work">Work</option><option value="relationships">Relationships</option>';
            html += '<option value="learning">Learning</option><option value="life_ops">Life Ops</option>';
            html += '<option value="finance">Finance</option>';
            html += '</select></div>';
            html += '</div>';
            // Results container
            html += '<div class="pkb-ctx-search-results" data-context-id="' + contextId + '" style="max-height:250px;overflow-y:auto;"></div>';
            html += '</div>';
            
            $c.html(html);
            
            // Bind unlink handlers
            $c.find('.pkb-ctx-unlink-claim').on('click', function() {
                var claimId = $(this).data('claim-id');
                removeClaimFromContext(contextId, claimId).done(function() {
                    showToast('Removed from context', 'success');
                    loadContextClaimsPanel(contextId);
                    // Refresh context count in the header
                    loadContextsTab();
                }).fail(function() {
                    showToast('Failed to remove', 'error');
                });
            });
            
            // Bind standard claim actions on linked claims
            bindClaimCardActions($c.find('.pkb-ctx-linked-claims'), function() {
                loadContextClaimsPanel(contextId);
            });
            
            // Bind search button, enter key, and filter changes
            $c.find('.pkb-ctx-search-btn').on('click', function() {
                performContextSearch(contextId, linkedIds);
            });
            $c.find('.pkb-ctx-search-input').on('keypress', function(e) {
                if (e.which === 13) performContextSearch(contextId, linkedIds);
            });
            $c.find('.pkb-ctx-filter-type, .pkb-ctx-filter-domain').on('change', function() {
                performContextSearch(contextId, linkedIds);
            });
            
        }).fail(function() {
            $c.html('<div class="text-center text-muted py-2">Failed to load memories.</div>');
        });
    }
    
    /**
     * Render a single linked claim row inside a context panel with an unlink button.
     *
     * @param {Object} claim - Claim object.
     * @param {string} contextId - Context UUID.
     * @returns {string} HTML string.
     */
    function renderContextLinkedClaimRow(claim, contextId) {
        var numBadge = claim.claim_number ? '<span class="badge badge-dark text-monospace mr-1">#' + claim.claim_number + '</span>' : '';
        var fidBadge = claim.friendly_id ? '<span class="badge badge-light text-monospace mr-1">@' + escapeHtml(claim.friendly_id) + '</span>' : '';
        
        return '<div class="list-group-item py-1 px-2 d-flex justify-content-between align-items-center" data-claim-id="' + claim.claim_id + '">' +
            '<div class="flex-grow-1">' +
                '<small>' + escapeHtml(claim.statement) + '</small><br>' +
                '<small class="text-muted">' + numBadge + fidBadge + renderClaimTypeBadge(claim.claim_type) + '</small>' +
            '</div>' +
            '<div class="btn-group btn-group-sm">' +
                '<button class="btn btn-outline-danger btn-sm pkb-ctx-unlink-claim" data-claim-id="' + claim.claim_id + '" data-context-id="' + contextId + '" title="Remove from context">' +
                    '<i class="bi bi-x-lg"></i>' +
                '</button>' +
            '</div>' +
        '</div>';
    }
    
    /**
     * Perform search within the context attach panel and render results with
     * link/unlink checkboxes.
     *
     * Handles multiple query styles:
     * - Empty query: list recent claims (respecting filters)
     * - #N, claim_N, @claim_N, bare number: resolve via /pkb/claims/by-friendly-id/
     * - @friendly_id: resolve via /pkb/claims/by-friendly-id/
     * - Free text: hybrid search via /pkb/search
     *
     * Reads filter dropdowns for type and domain and applies them.
     *
     * @param {string} contextId - Context UUID.
     * @param {Object} linkedIds - Map of already-linked claim IDs for checkbox state.
     */
    function performContextSearch(contextId, linkedIds) {
        var $input = $('.pkb-ctx-search-input[data-context-id="' + contextId + '"]');
        var $results = $('.pkb-ctx-search-results[data-context-id="' + contextId + '"]');
        var query = $input.val().trim();
        var filterType = $('.pkb-ctx-filter-type[data-context-id="' + contextId + '"]').val();
        var filterDomain = $('.pkb-ctx-filter-domain[data-context-id="' + contextId + '"]').val();
        
        $results.html('<div class="text-center py-2"><div class="spinner-border spinner-border-sm" role="status"></div></div>');
        
        // Detect ID-like queries: #N, claim_N, @claim_N, bare number, @friendly_id, UUID
        var idQuery = query.replace(/^[@#]/, '');  // strip leading @ or #
        var isIdLookup = /^(claim_)?\d+$/.test(idQuery) ||
                         /^[a-zA-Z0-9_-]{2,}$/.test(idQuery) && (query.startsWith('@') || query.startsWith('#'));
        
        if (isIdLookup && query) {
            // Try resolving as an identifier (number, claim_N, friendly_id, UUID)
            $.ajax({
                url: '/pkb/claims/by-friendly-id/' + encodeURIComponent(idQuery),
                method: 'GET',
                dataType: 'json'
            }).done(function(resp) {
                if (resp.claim) {
                    renderContextSearchResults(contextId, [resp.claim], linkedIds, $results);
                } else {
                    // Fall through to text search
                    doTextSearch(query, filterType, filterDomain, contextId, linkedIds, $results);
                }
            }).fail(function() {
                // Not found by ID, try text search
                doTextSearch(query, filterType, filterDomain, contextId, linkedIds, $results);
            });
            return;
        }
        
        // Empty or text query
        doTextSearch(query, filterType, filterDomain, contextId, linkedIds, $results);
    }
    
    /**
     * Execute a text-based search for the context attach panel.
     * If query is empty, lists recent claims with filters.
     * If query is present, uses hybrid search.
     */
    function doTextSearch(query, filterType, filterDomain, contextId, linkedIds, $results) {
        // Use the unified listClaims endpoint for both list and search modes
        var filters = { status: 'active' };
        if (filterType) filters.claim_type = filterType;
        if (filterDomain) filters.context_domain = filterDomain;
        
        listClaims(filters, 30, 0, query || undefined).done(function(resp) {
            renderContextSearchResults(contextId, resp.claims || [], linkedIds, $results);
        }).fail(function() {
            $results.html('<div class="text-muted small py-2">Search failed.</div>');
        });
    }
    
    /**
     * Render search results for the context attach panel.
     * Each result has a checkbox: checked = linked, unchecked = not linked.
     *
     * @param {string} contextId - Context UUID.
     * @param {Array} claims - Claims to render.
     * @param {Object} linkedIds - Map of already-linked claim IDs.
     * @param {jQuery} $container - Results container.
     */
    function renderContextSearchResults(contextId, claims, linkedIds, $container) {
        if (!claims || claims.length === 0) {
            $container.html('<div class="text-muted small py-2">No results found.</div>');
            return;
        }
        
        var html = '<div class="list-group list-group-flush">';
        claims.forEach(function(claim) {
            var isLinked = linkedIds[claim.claim_id] === true;
            var numBadge = claim.claim_number ? '#' + claim.claim_number + ' ' : '';
            var fidBadge = claim.friendly_id ? '@' + escapeHtml(claim.friendly_id) + ' ' : '';
            
            html += '<div class="list-group-item py-1 px-2 d-flex align-items-center pkb-ctx-search-row">' +
                '<div class="form-check mr-2">' +
                    '<input type="checkbox" class="form-check-input pkb-ctx-link-checkbox" ' +
                        'data-claim-id="' + claim.claim_id + '" data-context-id="' + contextId + '" ' +
                        (isLinked ? 'checked' : '') + '>' +
                '</div>' +
                '<div class="flex-grow-1">' +
                    '<small>' + escapeHtml(claim.statement) + '</small><br>' +
                    '<small class="text-muted">' + numBadge + fidBadge + renderClaimTypeBadge(claim.claim_type) +
                    ' <span class="badge badge-outline-secondary">' + claim.context_domain + '</span></small>' +
                '</div>' +
            '</div>';
        });
        html += '</div>';
        $container.html(html);
        
        // Bind checkbox change: link or unlink
        $container.find('.pkb-ctx-link-checkbox').on('change', function() {
            var claimId = $(this).data('claim-id');
            var ctxId = $(this).data('context-id');
            var isChecked = $(this).is(':checked');
            var $cb = $(this);
            
            if (isChecked) {
                // Link
                addClaimToContext(ctxId, claimId).done(function() {
                    linkedIds[claimId] = true;
                    showToast('Linked!', 'success');
                    loadContextClaimsPanel(ctxId);
                }).fail(function() {
                    $cb.prop('checked', false);
                    showToast('Failed to link', 'error');
                });
            } else {
                // Unlink
                removeClaimFromContext(ctxId, claimId).done(function() {
                    delete linkedIds[claimId];
                    showToast('Unlinked!', 'success');
                    loadContextClaimsPanel(ctxId);
                }).fail(function() {
                    $cb.prop('checked', true);
                    showToast('Failed to unlink', 'error');
                });
            }
        });
    }
    
    // Initialize on document ready
    $(document).ready(init);
    
    // ===========================================================================
    // Context Management (v0.5)
    // ===========================================================================
    
    /**
     * List all contexts for the current user.
     * @returns {jQuery.Deferred}
     */
    function listContexts() {
        return $.ajax({
            url: '/pkb/contexts',
            method: 'GET',
            dataType: 'json'
        });
    }
    
    /**
     * Create a new context.
     * @param {Object} data - {name, friendly_id?, description?, parent_context_id?, claim_ids?}
     * @returns {jQuery.Deferred}
     */
    function createContext(data) {
        return $.ajax({
            url: '/pkb/contexts',
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify(data),
            dataType: 'json'
        });
    }
    
    /**
     * Delete a context.
     * @param {string} contextId
     * @returns {jQuery.Deferred}
     */
    function deleteContext(contextId) {
        return $.ajax({
            url: '/pkb/contexts/' + contextId,
            method: 'DELETE',
            dataType: 'json'
        });
    }
    
    /**
     * Add a claim to a context.
     * @param {string} contextId
     * @param {string} claimId
     * @returns {jQuery.Deferred}
     */
    function addClaimToContext(contextId, claimId) {
        return $.ajax({
            url: '/pkb/contexts/' + contextId + '/claims',
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ claim_id: claimId }),
            dataType: 'json'
        });
    }
    
    /**
     * Remove a claim from a context.
     * @param {string} contextId
     * @param {string} claimId
     * @returns {jQuery.Deferred}
     */
    function removeClaimFromContext(contextId, claimId) {
        return $.ajax({
            url: '/pkb/contexts/' + contextId + '/claims/' + claimId,
            method: 'DELETE',
            dataType: 'json'
        });
    }
    
    /**
     * Resolve a context to get all claims recursively.
     * @param {string} contextId
     * @returns {jQuery.Deferred}
     */
    function resolveContext(contextId) {
        return $.ajax({
            url: '/pkb/contexts/' + contextId + '/resolve',
            method: 'GET',
            dataType: 'json'
        });
    }
    
    // ===========================================================================
    // Entity Management (v0.5)
    // ===========================================================================
    
    /**
     * Create a new entity.
     * @param {Object} data - {name, entity_type}
     * @returns {jQuery.Deferred}
     */
    function createEntity(data) {
        return $.ajax({
            url: '/pkb/entities',
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify(data),
            dataType: 'json'
        });
    }
    
    /**
     * Get entities linked to a claim.
     * @param {string} claimId
     * @returns {jQuery.Deferred}
     */
    function getClaimEntities(claimId) {
        return $.ajax({
            url: '/pkb/claims/' + claimId + '/entities',
            method: 'GET',
            dataType: 'json'
        });
    }
    
    /**
     * Link an entity to a claim.
     * @param {string} claimId
     * @param {string} entityId
     * @param {string} role - subject|object|mentioned|about_person
     * @returns {jQuery.Deferred}
     */
    function linkEntityToClaim(claimId, entityId, role) {
        return $.ajax({
            url: '/pkb/claims/' + claimId + '/entities',
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ entity_id: entityId, role: role || 'mentioned' }),
            dataType: 'json'
        });
    }
    
    /**
     * Unlink an entity from a claim.
     * @param {string} claimId
     * @param {string} entityId
     * @returns {jQuery.Deferred}
     */
    function unlinkEntityFromClaim(claimId, entityId) {
        return $.ajax({
            url: '/pkb/claims/' + claimId + '/entities/' + entityId,
            method: 'DELETE',
            dataType: 'json'
        });
    }
    
    // ===========================================================================
    // Autocomplete (v0.5)
    // ===========================================================================
    
    /**
     * Search for memories and contexts by friendly_id prefix.
     * Used for @autocomplete in chat input.
     * @param {string} prefix - Characters typed after @
     * @param {number} limit - Max results per category
     * @returns {jQuery.Deferred}
     */
    function searchAutocomplete(prefix, limit) {
        return $.ajax({
            url: '/pkb/autocomplete',
            method: 'GET',
            data: { q: prefix, limit: limit || 10 },
            dataType: 'json'
        });
    }
    
    /**
     * Get a claim by its friendly_id.
     * @param {string} friendlyId
     * @returns {jQuery.Deferred}
     */
    function getClaimByFriendlyId(friendlyId) {
        return $.ajax({
            url: '/pkb/claims/by-friendly-id/' + friendlyId,
            method: 'GET',
            dataType: 'json'
        });
    }
    
    // ===========================================================================
    // Load Contexts into UI
    // ===========================================================================
    
    /**
     * Load and render contexts in the Entities tab (reused as Entities & Contexts).
     */
    function loadContexts() {
        listContexts().done(function(response) {
            if (response.success && response.contexts) {
                var $list = $('#pkb-entities-list');
                if (response.contexts.length === 0) {
                    // Keep existing entity content, don't overwrite
                    return;
                }
                // Append contexts section after entities
                var contextHtml = '<div class="mt-3"><h6><i class="bi bi-folder"></i> Contexts</h6>';
                response.contexts.forEach(function(ctx) {
                    contextHtml += '<div class="list-group-item d-flex justify-content-between align-items-center">' +
                        '<div>' +
                            '<strong>' + escapeHtml(ctx.name) + '</strong>' +
                            ' <span class="badge badge-light text-monospace">@' + escapeHtml(ctx.friendly_id) + '</span>' +
                            (ctx.description ? '<br><small class="text-muted">' + escapeHtml(ctx.description) + '</small>' : '') +
                        '</div>' +
                        '<span class="badge badge-primary badge-pill">' + ctx.claim_count + ' memories</span>' +
                    '</div>';
                });
                contextHtml += '</div>';
                $list.append(contextHtml);
            }
        });
    }
    
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
        
        // Context Management (v0.5)
        listContexts: listContexts,
        createContext: createContext,
        deleteContext: deleteContext,
        addClaimToContext: addClaimToContext,
        removeClaimFromContext: removeClaimFromContext,
        resolveContext: resolveContext,
        loadContexts: loadContexts,
        
        // Entity Management (v0.5)
        createEntity: createEntity,
        getClaimEntities: getClaimEntities,
        linkEntityToClaim: linkEntityToClaim,
        unlinkEntityFromClaim: unlinkEntityFromClaim,
        
        // Autocomplete & Friendly ID (v0.5)
        searchAutocomplete: searchAutocomplete,
        getClaimByFriendlyId: getClaimByFriendlyId,
        
        // Utility
        showToast: showToast
    };
})();
