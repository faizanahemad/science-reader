// Complete Workspace Manager that integrates with existing server APIs
var WorkspaceManager = {
    workspaces: {},
    get defaultWorkspaceId() {
        // Compose the default workspace id similar to Python: f'default_{user_email}_{domain}'
        // Fallback to 'default' if userDetails or currentDomain are not available
        const email = (typeof userDetails !== 'undefined' && userDetails.email) ? userDetails.email : 'unknown';
        const domain = (typeof currentDomain !== 'undefined' && currentDomain['domain']) ? currentDomain['domain'] : 'unknown';
        return `default_${email}_${domain}`;
    },
    conversations: [],
    
    // Initialize workspace system
    init: function() {
        this.setupEventHandlers();
        this.setupDragAndDrop();
        this.setupContextMenus();
    },

    loadConversationsWithWorkspaces: function(autoselect = true) {
        // First, load all workspaces for the domain
        var workspacesRequest = $.ajax({
            url: '/list_workspaces/' + currentDomain['domain'],
            type: 'GET'
        });
        
        // Then, load all conversations  
        var conversationsRequest = $.ajax({
            url: '/list_conversation_by_user/' + currentDomain['domain'],
            type: 'GET'
        });
        
        // When both are loaded, combine them
        $.when(workspacesRequest, conversationsRequest).done((workspacesData, conversationsData) => {
            const workspaces = workspacesData[0]; // First element is the data
            const conversations = conversationsData[0]; // First element is the data
            
            // Sort conversations by last_updated in descending order
            conversations.sort((a, b) => new Date(b.last_updated) - new Date(a.last_updated));
            this.conversations = conversations;
            
            // Build workspaces map from the workspace API (includes empty workspaces)
            var workspacesMap = {};
            
            // Add all workspaces (including empty ones)
            workspaces.forEach(workspace => {
                workspacesMap[workspace.workspace_id] = {
                    workspace_id: workspace.workspace_id,
                    name: workspace.workspace_name,
                    color: workspace.workspace_color || 'primary',
                    is_default: workspace.workspace_id.startsWith(this.defaultWorkspaceId),
                    expanded: workspace.expanded === true || workspace.expanded === 'true' || workspace.expanded === 1
                };
            });
            
            // Ensure default workspace exists
            if (!workspacesMap[this.defaultWorkspaceId]) {
                workspacesMap[this.defaultWorkspaceId] = {
                    workspace_id: this.defaultWorkspaceId,
                    name: 'General',
                    color: 'primary',
                    is_default: true,
                    expanded: true
                };
            }
            
            // Group conversations by workspace
            var conversationsByWorkspace = {};
            
            // Initialize all workspaces with empty arrays
            Object.keys(workspacesMap).forEach(workspaceId => {
                conversationsByWorkspace[workspaceId] = [];
            });
            
            // Add conversations to their workspaces
            conversations.forEach(conversation => {
                var workspaceId = conversation.workspace_id || this.defaultWorkspaceId;
                if (conversationsByWorkspace[workspaceId]) {
                    conversationsByWorkspace[workspaceId].push(conversation);
                }
            });

            // *** NEW LOGIC START ***
            // Determine the last updated time for each workspace
            Object.values(workspacesMap).forEach(workspace => {
                const convosInWorkspace = conversationsByWorkspace[workspace.workspace_id];
                if (convosInWorkspace && convosInWorkspace.length > 0) {
                    // Since the main conversations array is already sorted by date,
                    // the first conversation in each group is the most recent one.
                    workspace.last_updated = convosInWorkspace[0].last_updated;
                } else {
                    // For empty workspaces, assign a very old date so they appear last.
                    workspace.last_updated = '1970-01-01T00:00:00.000Z';
                }
            });
            // *** NEW LOGIC END ***
            
            this.workspaces = workspacesMap;
            this.renderWorkspaces(conversationsByWorkspace);
            
            // Handle auto-selection (same as before)
            if (autoselect) {
                const conversationId = getConversationIdFromUrl();
                if (conversationId) {
                    ConversationManager.setActiveConversation(conversationId);
                    this.highlightActiveConversation(conversationId);
                } else if (conversations.length > 0) {
                    ConversationManager.setActiveConversation(conversations[0].conversation_id);
                    this.highlightActiveConversation(conversations[0].conversation_id);
                }
            } else {
                // When autoselect is false, preserve any existing active conversation
                const currentActive = ConversationManager.getActiveConversation();
                if (currentActive) {
                    this.highlightActiveConversation(currentActive);
                }
            }
            
            // Handle browser back/forward navigation (same as before)
            window.onpopstate = function(event) {
                if (event.state && event.state.conversationId) {
                    ConversationManager.setActiveConversation(event.state.conversationId);
                } else {
                    var currentConversationId = ConversationManager.getActiveConversation();
                    var previousUrl = window.history.previousUrl;
                    var previousConversationId = getConversationIdFromUrl(previousUrl);
                    
                    if (currentConversationId !== previousConversationId) {
                        window.history.back();
                    }
                }
            };
            
            // Handle search domain auto-stateless (same as before)
            if (currentDomain['domain'] === 'search') {
                var current_conversation = $('#workspaces-container').find('.conversation-item.active');
                current_conversation.find('.stateless-button').click();
            }
        }).fail(() => {
            console.error('Failed to load workspaces or conversations');
        });
        
        // Return a combined promise
        return $.when(workspacesRequest, conversationsRequest);
    },

    // Render workspace structure
    renderWorkspaces: function(conversationsByWorkspace) {
        const container = $('#workspaces-container');
        container.empty();
        
        // *** NEW SORTING LOGIC ***
        // Sort workspaces by their most recent conversation date, in descending order.
        const sortedWorkspaces = Object.values(this.workspaces).sort((a, b) => {
            return new Date(b.last_updated) - new Date(a.last_updated);
        });
        
        sortedWorkspaces.forEach(workspace => {
            const conversations = conversationsByWorkspace[workspace.workspace_id] || [];
            const workspaceElement = this.createWorkspaceElement(workspace, conversations);
            container.append(workspaceElement);
        });
        
        this.setupWorkspaceEventHandlers();
    },

    // Create individual workspace element with individual add button
    createWorkspaceElement: function(workspace, conversations) {
        const workspaceId = workspace.workspace_id;
        const safeCssId = workspaceId.replace(/[^\w-]/g, '_'); // Replace invalid chars with underscore
        
        // *** CHANGE THIS LINE ***
        // OLD: const isExpanded = localStorage.getItem(`workspace_${workspaceId}_expanded`) !== 'false';
        // NEW: Read 'expanded' state directly from the workspace object.
        const isExpanded = workspace.expanded === true || workspace.expanded === 'true';

        const workspaceDiv = $(`
            <div class="workspace-section workspace-color-${workspace.color}" data-workspace-id="${workspaceId}">
                <div class="workspace-header" data-workspace-id="${workspaceId}">
                    <div class="workspace-title">${workspace.name}</div>
                    <div class="workspace-header-actions">
                        <span class="workspace-count">${conversations.length}</span>
                        <button class="btn p-0 workspace-add-chat" data-workspace-id="${workspaceId}" title="Add chat to ${workspace.name}">
                            <i class="fa fa-plus" style="font-size: 0.8rem; color: #6c757d;"></i>
                        </button>
                        <i class="fa fa-chevron-down workspace-toggle ${isExpanded ? '' : 'collapsed'}" data-workspace-id="${workspaceId}" title="Expand/Collapse"></i>
                    </div>
                </div>
                <div class="collapse workspace-content ${isExpanded ? 'show' : ''}" id="workspace-${safeCssId}">
                    <div class="workspace-conversations" data-workspace-id="${workspaceId}">
                        <div class="drop-indicator"></div>
                    </div>
                </div>
            </div>
        `);
        
        const conversationsContainer = workspaceDiv.find('.workspace-conversations');
        conversations.forEach(conversation => {
            const conversationElement = this.createConversationElement(conversation);
            conversationsContainer.append(conversationElement);
        });
        
        return workspaceDiv;
    },

    // Create conversation element with all existing functionality preserved
    createConversationElement: function(conversation) {
        const conversationItem = $(`
            <a href="#" class="list-group-item list-group-item-action conversation-item" 
               data-conversation-id="${conversation.conversation_id}" 
               draggable="true">
                <div class="d-flex justify-content-between align-items-start">
                    <div class="conversation-content flex-grow-1">
                        <strong class="conversation-title-in-sidebar">${conversation.title.slice(0, 45).trim()}</strong>
                        <div class="conversation-summary" style="font-size: 0.75rem; color: #6c757d; margin-top: 2px; line-height: 1.2;">
                            ${conversation.summary_till_now ? conversation.summary_till_now.slice(0, 60) + '...' : ''}
                        </div>
                    </div>
                    <div class="conversation-actions d-flex">
                        <button class="btn p-0 ms-1 clone-conversation-button" data-conversation-id="${conversation.conversation_id}" title="Clone">
                            <i class="bi bi-clipboard" style="font-size: 0.8rem;"></i>
                        </button>
                        <button class="btn p-0 ms-1 delete-chat-button" data-conversation-id="${conversation.conversation_id}" title="Delete">
                            <i class="bi bi-trash-fill" style="font-size: 0.8rem;"></i>
                        </button>
                        <button class="btn p-0 ms-1 stateless-button" data-conversation-id="${conversation.conversation_id}" title="Toggle State">
                            <i class="bi bi-eye-slash" style="font-size: 0.8rem;"></i>
                        </button>
                    </div>
                </div>
            </a>
        `);
        
        return conversationItem;
    },

    // Setup main event handlers
    setupEventHandlers: function() {
        // Add new workspace button
        $('#add-new-workspace').off('click').on('click', () => {
            this.showCreateWorkspaceModal();
        });
        
        // Update existing create conversation to use current workspace or default
        $('#add-new-chat').off('click').on('click', () => {
            this.createConversationInCurrentWorkspace();
        });
    },

    // Create conversation in currently expanded workspace or default
    createConversationInCurrentWorkspace: function() {
        // Find currently expanded workspace or use default
        var targetWorkspaceId = null;
        // The .workspace-content element does not have data-workspace-id.
        // Instead, its parent .workspace-section has the data-workspace-id attribute.
        // We need to get the parent .workspace-section and read its data-workspace-id.
        $('.workspace-content.show').each(function() {
            const workspaceSection = $(this).closest('.workspace-section');
            const workspaceId = workspaceSection.data('workspace-id');
            if (workspaceId) {
                targetWorkspaceId = workspaceId;
            }
        });
        
        if (!targetWorkspaceId) {
            targetWorkspaceId = this.defaultWorkspaceId;
        }
        
        this.createConversationInWorkspace(targetWorkspaceId);
    },

    // Create conversation in specific workspace
    createConversationInWorkspace: function(workspaceId) {
        $.ajax({
            url: '/create_conversation/' + currentDomain['domain'] + '/' + workspaceId,
            type: 'POST',
            success: (conversation) => {
                $('#linkInput').val('')
                $('#searchInput').val('')
                // Reload conversations to show the new one
                this.loadConversationsWithWorkspaces(true).done(() => {
                    ConversationManager.setActiveConversation(conversation.conversation_id);
                    this.highlightActiveConversation(conversation.conversation_id);
                    this.expandWorkspace(workspaceId, true);
                });
            }
        });
    },

    collapseAllWorkspaces: function(exceptWorkspaceId) {
        // Get all workspace IDs except the one we are about to expand
        const idsToCollapse = Object.keys(this.workspaces).filter(id => id !== exceptWorkspaceId);

        // Visually collapse them in the UI immediately for a responsive feel
        idsToCollapse.forEach(id => {
            const safeCssId = id.replace(/[^\w-]/g, '_');
            const content = $(`#workspace-${safeCssId}`);
            if (content.hasClass('show')) {
                content.collapse('hide');
                const toggle = $(`.workspace-toggle[data-workspace-id="${id}"]`);
                toggle.addClass('collapsed');
            }
        });

        // Call the server to persist the collapsed state for all other workspaces
        return $.ajax({
            url: '/collapse_workspaces',
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({
                workspace_ids: idsToCollapse
            }),
            success: function() {
                console.log('All other workspaces collapsed successfully on the server.');
            },
            error: function() {
                console.error('Failed to collapse other workspaces on the server.');
            }
        });
    },

    expandWorkspace: function(workspaceId, shouldExpand = true) {
        if (shouldExpand) {
            // First, collapse all other workspaces.
            this.collapseAllWorkspaces(workspaceId).done(() => {
                // After others are collapsed, proceed to expand the target one.
                this.setWorkspaceExpansionState(workspaceId, true);
            });
        } else {
            // If we are explicitly collapsing, just do it.
            this.setWorkspaceExpansionState(workspaceId, false);
        }
    },

    // *** ADD THIS NEW HELPER FUNCTION for setting the state ***
    setWorkspaceExpansionState: function(workspaceId, isExpanded) {
        const safeCssId = workspaceId.replace(/[^\w-]/g, '_');
        const content = $(`#workspace-${safeCssId}`);
        const toggle = $(`.workspace-toggle[data-workspace-id="${workspaceId}"]`);
        
        const isCurrentlyExpanded = content.hasClass('show');

        // Only act if a change is needed
        if (isExpanded === isCurrentlyExpanded) {
            return;
        }

        if (isExpanded) {
            content.collapse('show');
            toggle.removeClass('collapsed');
        } else {
            content.collapse('hide');
            toggle.addClass('collapsed');
        }
        
        // Persist the new state to the server for the target workspace
        $.ajax({
            url: '/update_workspace/' + workspaceId,
            type: 'PUT',
            contentType: 'application/json',
            data: JSON.stringify({ expanded: isExpanded }),
            success: function() {
                console.log(`Workspace ${workspaceId} expanded state saved to ${isExpanded}`);
            },
            error: function() {
                console.error(`Failed to save state for workspace ${workspaceId}`);
            }
        });
    },

    // Setup workspace-specific event handlers
    setupWorkspaceEventHandlers: function() {
        // Use event delegation instead of direct binding - this handles dynamically created elements
        
        // Workspace toggle click (using event delegation)
        $(document).off('click', '.workspace-toggle').on('click', '.workspace-toggle', function(e) {
            e.preventDefault();
            e.stopPropagation();
            
            const workspaceId = $(this).data('workspace-id');
            const isCurrentlyExpanded = !$(this).hasClass('collapsed');

            // Call our central function to handle the logic.
            // If it's already expanded, this call will collapse it.
            WorkspaceManager.expandWorkspace(workspaceId, !isCurrentlyExpanded);
        });
        
        // Also update the workspace header click handler
        $(document).off('click', '.workspace-header').on('click', '.workspace-header', function(e) {
            if ($(e.target).closest('.workspace-add-chat, .workspace-header-actions').length) return;
            
            const workspaceId = $(this).data('workspace-id');
            const isCurrentlyExpanded = !$(this).find('.workspace-toggle').hasClass('collapsed');
            
            // Call our central function here as well.
            WorkspaceManager.expandWorkspace(workspaceId, !isCurrentlyExpanded);
        });
    
        // Individual workspace add chat buttons (using event delegation)
        $(document).off('click', '.workspace-add-chat').on('click', '.workspace-add-chat', function(e) {
            e.preventDefault();
            e.stopPropagation();
            const workspaceId = $(this).data('workspace-id');
            WorkspaceManager.createConversationInWorkspace(workspaceId);
        });
        
        // Conversation click handlers (using event delegation)
        $(document).off('click', '.conversation-item').on('click', '.conversation-item', function(e) {
            if ($(e.target).closest('button').length) return;
            
            const conversationId = $(this).data('conversation-id');
            
            // Highlight this conversation immediately
            WorkspaceManager.highlightActiveConversation(conversationId);
            
            ConversationManager.setActiveConversation(conversationId);
        });
        
        // Clone conversation button (using event delegation)
        $(document).off('click', '.clone-conversation-button').on('click', '.clone-conversation-button', function(e) {
            e.preventDefault();
            e.stopPropagation();
            const conversationId = $(this).data('conversation-id');

            // The AJAX call now returns the server response directly.
            ConversationManager.cloneConversation(conversationId).done((clonedConversation) => {
                // Now that the clone is created, reload the sidebar.
                // We use 'false' for autoselect because we want to manually select the new clone.
                WorkspaceManager.loadConversationsWithWorkspaces(false).done(() => {
                    // After the sidebar is re-rendered, set the new conversation as active.
                    ConversationManager.setActiveConversation(clonedConversation.conversation_id);
                    // The highlight is now handled by other logic, but we can call it 
                    // explicitly here to guarantee the new item is highlighted.
                    WorkspaceManager.highlightActiveConversation(clonedConversation.conversation_id);
                });
            });
        });
        
        // Delete conversation button (using event delegation)
        $(document).off('click', '.delete-chat-button').on('click', '.delete-chat-button', function(e) {
            e.preventDefault();
            e.stopPropagation();
            const conversationId = $(this).data('conversation-id');
            
            // Remove from UI immediately
            $(this).closest('.conversation-item').remove();
            
            // Update workspace count
            const workspaceId = $(this).closest('.workspace-conversations').data('workspace-id');
            const countElement = $(`.workspace-header[data-workspace-id="${workspaceId}"] .workspace-count`);
            const currentCount = parseInt(countElement.text()) || 0;
            countElement.text(Math.max(0, currentCount - 1));
            
            // Call server
            $.ajax({
                url: '/delete_conversation/' + conversationId,
                type: 'DELETE',
                success: (result) => {
                    // Handle active conversation deletion
                    if (ConversationManager.activeConversationId == conversationId) {
                        const firstConversation = $('.conversation-item:first');
                        if (firstConversation.length) {
                            const firstConversationId = firstConversation.data('conversation-id');
                            ConversationManager.setActiveConversation(firstConversationId);
                        }
                    }
                },
                error: () => {
                    // Reload on error
                    WorkspaceManager.loadConversationsWithWorkspaces(true);
                }
            });
        });
        
        // Stateless/stateful button (using event delegation)
        $(document).off('click', '.stateless-button').on('click', '.stateless-button', function(e) {
            e.preventDefault();
            e.stopPropagation();
            const conversationId = $(this).data('conversation-id');
            const button = $(this);
            
            if (button.find('i').hasClass('bi-eye-slash')) {
                ConversationManager.statelessConversation(conversationId).done(() => {
                    button.find('i').removeClass('bi-eye-slash').addClass('bi-eye');
                });
            } else {
                ConversationManager.statefulConversation(conversationId).done(() => {
                    button.find('i').removeClass('bi-eye').addClass('bi-eye-slash');
                });
            }
        });
        
        // Right-click context menu for workspaces (using event delegation)
        $(document).off('contextmenu', '.workspace-header').on('contextmenu', '.workspace-header', function(e) {
            e.preventDefault();
            const workspaceId = $(this).data('workspace-id');
            if (workspaceId === WorkspaceManager.defaultWorkspaceId) return;
            
            WorkspaceManager.showWorkspaceContextMenu(e.pageX, e.pageY, workspaceId);
        });
        
        // Right-click context menu for conversations (using event delegation)
        $(document).off('contextmenu', '.conversation-item').on('contextmenu', '.conversation-item', function(e) {
            e.preventDefault();
            const conversationId = $(this).data('conversation-id');
            WorkspaceManager.showConversationContextMenu(e.pageX, e.pageY, conversationId);
        });
    },

    // Setup drag and drop functionality
    // Replace the entire setupDragAndDrop function with this new version
    setupDragAndDrop: function() {
        const container = document.getElementById('workspaces-container');
        if (!container) {
            console.error("Workspace container not found for drag-and-drop setup.");
            return;
        }

        let draggedElement = null;
        let sourceWorkspaceId = null;

        // 1. DRAG START: Fired once when dragging begins.
        $(document).off('dragstart', '.conversation-item').on('dragstart', '.conversation-item', function(e) {
            draggedElement = this; // Store the actual DOM element
            sourceWorkspaceId = $(this).closest('.workspace-conversations').data('workspace-id');

            e.originalEvent.dataTransfer.setData('text/plain', $(this).data('conversation-id'));
            e.originalEvent.dataTransfer.effectAllowed = 'move';

            // Use a tiny timeout to apply the class. This prevents visual glitches.
            setTimeout(() => {
                $(draggedElement).addClass('conversation-dragging');
            }, 0);
            
            console.log('Drag started for:', $(this).data('conversation-id'), 'from:', sourceWorkspaceId);
        });

        // 2. DRAG OVER: Fired continuously as you drag over an element.
        // We use a native event listener on the parent container for maximum reliability.
        container.removeEventListener('dragover', WorkspaceManager.dragOverHandler); // Remove old listener if any
        WorkspaceManager.dragOverHandler = function(e) {
            e.preventDefault(); // This is THE MOST CRITICAL PART. It allows dropping.
            
            const targetWorkspace = e.target.closest('.workspace-section');
            
            // Clear previous drop targets
            $('.workspace-drop-zone').removeClass('workspace-drop-zone');

            if (targetWorkspace) {
                const targetWorkspaceId = targetWorkspace.dataset.workspaceId;
                
                // Highlight if it's a valid, different workspace
                if (targetWorkspaceId && targetWorkspaceId !== sourceWorkspaceId) {
                    e.dataTransfer.dropEffect = 'move';
                    targetWorkspace.classList.add('workspace-drop-zone');
                } else {
                    // Not a valid drop target (e.g., same workspace)
                    e.dataTransfer.dropEffect = 'none';
                }
            }
        };
        container.addEventListener('dragover', WorkspaceManager.dragOverHandler);

        // 3. DROP: Fired once when the item is released over a valid drop target.
        container.removeEventListener('drop', WorkspaceManager.dropHandler); // Remove old listener if any
        WorkspaceManager.dropHandler = function(e) {
            e.preventDefault(); // Also important to prevent default browser action (like opening a link)
            
            const targetWorkspace = e.target.closest('.workspace-section');
            $('.workspace-drop-zone').removeClass('workspace-drop-zone'); // Clean up UI

            if (targetWorkspace && draggedElement) {
                const targetWorkspaceId = targetWorkspace.dataset.workspaceId;
                const conversationId = e.dataTransfer.getData('text/plain');

                // Final check to ensure it's a different workspace
                if (targetWorkspaceId && sourceWorkspaceId && targetWorkspaceId !== sourceWorkspaceId) {
                    console.log('Drop successful. Moving', conversationId, 'to', targetWorkspaceId);
                    
                    $(draggedElement).addClass('moving-conversation');
                    
                    WorkspaceManager.moveConversationToWorkspace(conversationId, targetWorkspaceId)
                        .always(() => {
                            // Always remove class, even on failure
                            $(draggedElement).removeClass('moving-conversation');
                        });
                } else {
                    console.log('Drop on same workspace or invalid target. No action.');
                }
            }
        };
        container.addEventListener('drop', WorkspaceManager.dropHandler);

        // 4. DRAG END: Fired once when the drag operation finishes (success or cancel).
        $(document).off('dragend', '.conversation-item').on('dragend', '.conversation-item', function(e) {
            console.log('Drag ended');
            // This is just for cleanup.
            $(this).removeClass('conversation-dragging');
            $('.workspace-drop-zone').removeClass('workspace-drop-zone');
            draggedElement = null;
            sourceWorkspaceId = null;
        });
    },

    // Setup context menus
    setupContextMenus: function() {
        // Hide context menus on document click
        $(document).on('click', function() {
            $('.context-menu').hide();
        });
    },

    // Show workspace context menu
    showWorkspaceContextMenu: function(x, y, workspaceId) {
        const menu = $('#workspace-context-menu');
        menu.css({
            top: y + 'px',
            left: x + 'px'
        }).show();
        
        menu.data('workspace-id', workspaceId);
        
        $('#rename-workspace').off('click').on('click', () => {
            this.showRenameWorkspaceModal(workspaceId);
            menu.hide();
        });
        
        $('#delete-workspace').off('click').on('click', () => {
            this.deleteWorkspace(workspaceId);
            menu.hide();
        });
        
        $('#change-workspace-color').off('click').on('click', () => {
            this.showWorkspaceColorModal(workspaceId);
            menu.hide();
        });
    },

    // Show conversation context menu
    showConversationContextMenu: function(x, y, conversationId) {
        const menu = $('#conversation-context-menu');
        
        // Populate workspace submenu
        const submenu = $('#workspace-submenu');
        submenu.empty();
        
        Object.values(this.workspaces).forEach(workspace => {
            submenu.append(`
                <li><a href="#" data-workspace-id="${workspace.workspace_id}" data-conversation-id="${conversationId}">
                    ${workspace.name}
                </a></li>
            `);
        });
        
        menu.css({
            top: y + 'px',
            left: x + 'px'
        }).show();
        
        // Handle workspace selection
        $('#workspace-submenu a').off('click').on('click', function(e) {
            e.preventDefault();
            const targetWorkspaceId = $(this).data('workspace-id');
            const conversationId = $(this).data('conversation-id');
            WorkspaceManager.moveConversationToWorkspace(conversationId, targetWorkspaceId);
            menu.hide();
        });
    },

    // Workspace CRUD operations
    createWorkspace: function(name, color = 'primary') {
        return $.ajax({
            url: '/create_workspace/' + currentDomain['domain'] + '/' + encodeURIComponent(name),
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({
                workspace_color: color
            }),
            success: () => {
                this.loadConversationsWithWorkspaces(false);
            }
        });
    },

    renameWorkspace: function(workspaceId, newName) {
        return $.ajax({
            url: '/update_workspace/' + workspaceId,
            type: 'PUT',
            contentType: 'application/json',
            data: JSON.stringify({
                workspace_name: newName
            }),
            success: () => {
                this.loadConversationsWithWorkspaces(false);
            }
        });
    },

    updateWorkspaceColor: function(workspaceId, newColor) {
        return $.ajax({
            url: '/update_workspace/' + workspaceId,
            type: 'PUT',
            contentType: 'application/json',
            data: JSON.stringify({
                workspace_color: newColor
            }),
            success: () => {
                this.loadConversationsWithWorkspaces(false);
            }
        });
    },

    deleteWorkspace: function(workspaceId) {
        if (workspaceId === this.defaultWorkspaceId) {
            alert('Cannot delete the default workspace');
            return;
        }
        
        if (confirm('Are you sure you want to delete this workspace? All conversations will be moved to General.')) {
            return $.ajax({
                url: '/delete_workspace/' + currentDomain['domain'] + '/' + workspaceId,
                type: 'DELETE',
                success: () => {
                    this.loadConversationsWithWorkspaces(false);
                }
            });
        }
    },

    moveConversationToWorkspace: function(conversationId, targetWorkspaceId) {
        return $.ajax({
            url: '/move_conversation_to_workspace/' + conversationId,
            type: 'PUT',
            contentType: 'application/json',
            data: JSON.stringify({
                workspace_id: targetWorkspaceId
            }),
            success: () => {
                // Store the currently active conversation
                const currentActiveConversation = ConversationManager.getActiveConversation();
                
                // Reload conversations to reflect the change
                this.loadConversationsWithWorkspaces(false).done(() => {
                    // Restore the active conversation selection after reload
                    if (currentActiveConversation) {
                        // Small delay to ensure DOM is updated
                        setTimeout(() => {
                            this.highlightActiveConversation(currentActiveConversation);
                            
                            // If the moved conversation was the active one, make sure it's still active
                            if (currentActiveConversation === conversationId) {
                                ConversationManager.activeConversationId = conversationId;
                            }
                        }, 100);
                    }
                });
            },
            error: (xhr, status, error) => {
                console.error('Failed to move conversation:', error);
                alert('Failed to move conversation to workspace. Please try again.');
            }
        });
    },

    // Modal functions
    /**
     * Show the modal dialog for creating a new workspace.
     * Ensures that both the cancel and dismiss (cross) buttons work as expected,
     * and that the dismiss button has a proper icon.
     */
    showCreateWorkspaceModal: function() {
        // Build the modal HTML with a proper cross icon for the dismiss button
        const modal = $(`
            <div class="modal fade" id="create-workspace-modal" tabindex="-1" aria-labelledby="createWorkspaceModalLabel" aria-hidden="true">
                <div class="modal-dialog">
                    <div class="modal-content">
                        <div class="modal-header">
                            <h5 class="modal-title" id="createWorkspaceModalLabel">Create New Workspace</h5>
                            <button type="button" class="btn-close" data-bs-dismiss="modal" id="close-create-workspace-btn" aria-label="Close">
                                <span aria-hidden="true">&times;</span>
                            </button>
                        </div>
                        <div class="modal-body">
                            <div class="mb-3">
                                <label for="workspace-name" class="form-label">Workspace Name</label>
                                <input type="text" class="form-control" id="workspace-name" placeholder="Enter workspace name">
                            </div>
                            <div class="mb-3">
                                <label for="workspace-color" class="form-label">Color</label>
                                <select class="form-select" id="workspace-color">
                                    <option value="primary">Blue</option>
                                    <option value="success">Green</option>
                                    <option value="danger">Red</option>
                                    <option value="warning">Yellow</option>
                                    <option value="info">Cyan</option>
                                    <option value="purple">Purple</option>
                                    <option value="pink">Pink</option>
                                    <option value="orange">Orange</option>
                                </select>
                            </div>
                        </div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-secondary" id="cancel-create-workspace-btn">Cancel</button>
                            <button type="button" class="btn btn-primary" id="create-workspace-btn">Create</button>
                        </div>
                    </div>
                </div>
            </div>
        `);

        // Append modal to body and show it
        $('body').append(modal);
        modal.modal('show');

        // Handle create button
        $('#create-workspace-btn').on('click', () => {
            const name = $('#workspace-name').val().trim();
            const color = $('#workspace-color').val();

            if (name) {
                this.createWorkspace(name, color);
                modal.modal('hide');
            }
        });

        // Handle cancel button
        $('#cancel-create-workspace-btn').on('click', () => {
            modal.modal('hide');
        });

        // Handle dismiss button
        $('#close-create-workspace-btn').on('click', () => {
            modal.modal('hide');
        });

        // Ensure modal is removed from DOM after hiding
        modal.on('hidden.bs.modal', () => {
            modal.remove();
        });
    },

    showRenameWorkspaceModal: function(workspaceId) {
        const workspace = this.workspaces[workspaceId];
        
        const modal = $(`
            <div class="modal fade" id="rename-workspace-modal" tabindex="-1">
                <div class="modal-dialog">
                    <div class="modal-content">
                        <div class="modal-header">
                            <h5 class="modal-title">Rename Workspace</h5>
                            <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                        </div>
                        <div class="modal-body">
                            <div class="mb-3">
                                <label for="workspace-rename" class="form-label">Workspace Name</label>
                                <input type="text" class="form-control" id="workspace-rename" value="${workspace.name}">
                            </div>
                        </div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
                            <button type="button" class="btn btn-primary" id="rename-workspace-btn">Rename</button>
                        </div>
                    </div>
                </div>
            </div>
        `);
        
        $('body').append(modal);
        modal.modal('show');
        
        $('#rename-workspace-btn').on('click', () => {
            const newName = $('#workspace-rename').val().trim();
            
            if (newName && newName !== workspace.name) {
                this.renameWorkspace(workspaceId, newName);
                modal.modal('hide');
            }
        });
        
        modal.on('hidden.bs.modal', () => {
            modal.remove();
        });
    },

    showWorkspaceColorModal: function(workspaceId) {
        const workspace = this.workspaces[workspaceId];
        
        const modal = $(`
            <div class="modal fade" id="color-workspace-modal" tabindex="-1">
                <div class="modal-dialog">
                    <div class="modal-content">
                        <div class="modal-header">
                            <h5 class="modal-title">Change Workspace Color</h5>
                            <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                        </div>
                        <div class="modal-body">
                            <div class="mb-3">
                                <label for="workspace-color-change" class="form-label">Color</label>
                                <select class="form-select" id="workspace-color-change">
                                    <option value="primary" ${workspace.color === 'primary' ? 'selected' : ''}>Blue</option>
                                    <option value="success" ${workspace.color === 'success' ? 'selected' : ''}>Green</option>
                                    <option value="danger" ${workspace.color === 'danger' ? 'selected' : ''}>Red</option>
                                    <option value="warning" ${workspace.color === 'warning' ? 'selected' : ''}>Yellow</option>
                                    <option value="info" ${workspace.color === 'info' ? 'selected' : ''}>Cyan</option>
                                    <option value="purple" ${workspace.color === 'purple' ? 'selected' : ''}>Purple</option>
                                    <option value="pink" ${workspace.color === 'pink' ? 'selected' : ''}>Pink</option>
                                    <option value="orange" ${workspace.color === 'orange' ? 'selected' : ''}>Orange</option>
                                </select>
                            </div>
                        </div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
                            <button type="button" class="btn btn-primary" id="color-workspace-btn">Change</button>
                        </div>
                    </div>
                </div>
            </div>
        `);
        
        $('body').append(modal);
        modal.modal('show');
        
        $('#color-workspace-btn').on('click', () => {
            const newColor = $('#workspace-color-change').val();
            
            if (newColor !== workspace.color) {
                this.updateWorkspaceColor(workspaceId, newColor);
                modal.modal('hide');
            }
        });
        
        modal.on('hidden.bs.modal', () => {
            modal.remove();
        });
    },
    highlightActiveConversation: function(conversationId) {
        // Remove highlight from all conversations
        $('.conversation-item').removeClass('active');
        
        // Add highlight to the active conversation
        $(`.conversation-item[data-conversation-id="${conversationId}"]`).addClass('active');
    },
};



// Initialize workspace system when document is ready
$(document).ready(function() {
    WorkspaceManager.init();
});