/**
 * WorkspaceManager — jsTree-based sidebar for hierarchical workspaces.
 *
 * Uses jsTree (jQuery plugin) with contextmenu, types, wholerow and search
 * plugins to render a VS Code-like file explorer in the sidebar.
 *
 * Node conventions:
 *   - workspace nodes:   id = "ws_<workspace_id>",  type = "workspace"
 *   - conversation nodes: id = "cv_<conversation_id>", type = "conversation"
 *
 * All existing features are preserved:
 *   flag, clone, delete, toggle stateless, deep link, mobile interceptor,
 *   auto-select, create workspace / sub-workspace, create conversation,
 *   move conversation, move workspace, rename, color, expand/collapse.
 */
var WorkspaceManager = {
    workspaces: {},
    _mobileConversationInterceptorInstalled: false,
    _jsTreeReady: false,
    _pendingHighlight: null,

    get defaultWorkspaceId() {
        var email = (typeof userDetails !== 'undefined' && userDetails.email) ? userDetails.email : 'unknown';
        var domain = (typeof currentDomain !== 'undefined' && currentDomain['domain']) ? currentDomain['domain'] : 'unknown';
        return 'default_' + email + '_' + domain;
    },

    conversations: [],

    // ---------------------------------------------------------------
    // Initialisation
    // ---------------------------------------------------------------
    init: function () {
        this.installMobileConversationInterceptor();
        this.setupToolbarHandlers();
    },

    // ---------------------------------------------------------------
    // Mobile capture-phase interceptor (unchanged)
    // ---------------------------------------------------------------
    installMobileConversationInterceptor: function () {
        if (this._mobileConversationInterceptorInstalled) return;
        this._mobileConversationInterceptorInstalled = true;

        var lastTouchTs = 0;
        var CLICK_AFTER_TOUCH_MS = 700;

        function isMobileWidth() {
            try { return window.matchMedia && window.matchMedia('(max-width: 768px)').matches; }
            catch (_e) { return (window.innerWidth || 9999) <= 768; }
        }

        function hideSidebarIfMobileOpen() {
            try {
                if (!isMobileWidth()) return;
                var sidebar = $('#chat-assistant-sidebar');
                var contentCol = $('#chat-assistant');
                if (sidebar.length && contentCol.length && !sidebar.hasClass('d-none')) {
                    sidebar.addClass('d-none');
                    contentCol.removeClass('col-md-10').addClass('col-md-12');
                    $(window).trigger('resize');
                }
            } catch (_e) { /* ignore */ }
        }

        function handler(e) {
            try {
                if (!isMobileWidth()) return;
                if (e.type === 'touchend') lastTouchTs = Date.now();
                if (e.type === 'click' && (Date.now() - lastTouchTs) < CLICK_AFTER_TOUCH_MS) return;

                var target = e.target;
                if (!target || !target.closest) return;
                if (target.closest('button')) return;

                // jsTree renders anchors inside <li> nodes – look for a conversation node.
                var li = target.closest('li.jstree-node');
                if (!li) return;
                var nodeId = li.getAttribute('id');
                if (!nodeId || nodeId.indexOf('cv_') !== 0) return;

                if (e.__conversationItemHandled) return;
                if (e.which === 2 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;

                e.__conversationItemHandled = true;
                if (e.cancelable) e.preventDefault();
                if (e.stopPropagation) e.stopPropagation();
                if (e.stopImmediatePropagation) e.stopImmediatePropagation();

                var conversationId = nodeId.substring(3);
                if (!conversationId) return;
                hideSidebarIfMobileOpen();

                var currentActive = (ConversationManager.getActiveConversation && ConversationManager.getActiveConversation()) || ConversationManager.activeConversationId || null;
                if (currentActive && String(currentActive) === String(conversationId)) return;

                WorkspaceManager.highlightActiveConversation(conversationId);
                ConversationManager.setActiveConversation(conversationId);
            } catch (_e) { /* best-effort */ }
        }

        try { document.addEventListener('touchend', handler, { capture: true, passive: false }); } catch (_e) {}
        try { document.addEventListener('pointerup', handler, true); } catch (_e) {}
        try { document.addEventListener('click', handler, true); } catch (_e) {}
    },

    // ---------------------------------------------------------------
    // Toolbar buttons (file+ / folder+)
    // ---------------------------------------------------------------
    setupToolbarHandlers: function () {
        var self = this;
        $('#add-new-workspace').off('click').on('click', function () {
            // Toolbar folder+ always creates a top-level workspace
            self.showCreateWorkspaceModal(null);
        });
        $('#add-new-chat').off('click').on('click', function () {
            var targetWs = self.getSelectedWorkspaceId() || self.defaultWorkspaceId;
            self.createConversationInWorkspace(targetWs);
        });
    },

    /**
     * Return the real workspace_id of the currently selected workspace node
     * in the jsTree (or null if none / a conversation is selected).
     */
    getSelectedWorkspaceId: function () {
        var tree = $('#workspaces-container').jstree(true);
        if (!tree) return null;
        var sel = tree.get_selected();
        if (!sel || !sel.length) return null;
        var nodeId = sel[0];
        if (nodeId.indexOf('ws_') === 0) return nodeId.substring(3);
        // If a conversation is selected, return its parent workspace
        var node = tree.get_node(nodeId);
        if (node && node.parent && node.parent.indexOf('ws_') === 0) return node.parent.substring(3);
        return null;
    },

    // ---------------------------------------------------------------
    // Data loading (AJAX – unchanged logic)
    // ---------------------------------------------------------------
    loadConversationsWithWorkspaces: function (autoselect) {
        if (typeof autoselect === 'undefined') autoselect = true;

        var workspacesRequest = $.ajax({ url: '/list_workspaces/' + currentDomain['domain'], type: 'GET' });
        var conversationsRequest = $.ajax({ url: '/list_conversation_by_user/' + currentDomain['domain'], type: 'GET' });

        $.when(workspacesRequest, conversationsRequest).done(function (workspacesData, conversationsData) {
            var workspaces = workspacesData[0];
            var conversations = conversationsData[0];
            conversations.sort(function (a, b) { return new Date(b.last_updated) - new Date(a.last_updated); });
            WorkspaceManager.conversations = conversations;

            var workspacesMap = {};
            workspaces.forEach(function (ws) {
                workspacesMap[ws.workspace_id] = {
                    workspace_id: ws.workspace_id,
                    name: ws.workspace_name,
                    color: ws.workspace_color || 'primary',
                    is_default: ws.workspace_id === WorkspaceManager.defaultWorkspaceId,
                    expanded: ws.expanded === true || ws.expanded === 'true' || ws.expanded === 1,
                    parent_workspace_id: ws.parent_workspace_id || null
                };
            });

            if (!workspacesMap[WorkspaceManager.defaultWorkspaceId]) {
                workspacesMap[WorkspaceManager.defaultWorkspaceId] = {
                    workspace_id: WorkspaceManager.defaultWorkspaceId,
                    name: 'General',
                    color: 'primary',
                    is_default: true,
                    expanded: true,
                    parent_workspace_id: null
                };
            }

            // Group conversations by workspace
            var convByWs = {};
            Object.keys(workspacesMap).forEach(function (id) { convByWs[id] = []; });
            conversations.forEach(function (c) {
                var wsId = c.workspace_id || WorkspaceManager.defaultWorkspaceId;
                if (convByWs[wsId]) convByWs[wsId].push(c);
            });

            WorkspaceManager.workspaces = workspacesMap;
            WorkspaceManager.renderTree(convByWs);

            // Auto-selection logic (same as before)
            if (autoselect) {
                var conversationId = getConversationIdFromUrl();
                if (conversationId) {
                    ConversationManager.setActiveConversation(conversationId);
                    WorkspaceManager.highlightActiveConversation(conversationId);
                } else if (conversations.length > 0) {
                    var resumeId = null;
                    try {
                        var email = (typeof userDetails !== 'undefined' && userDetails && userDetails.email) ? String(userDetails.email) : 'unknown';
                        var domain = (typeof currentDomain !== 'undefined' && currentDomain && currentDomain['domain']) ? String(currentDomain['domain']) : 'unknown';
                        var key = 'lastActiveConversationId:' + email + ':' + domain;
                        resumeId = localStorage.getItem(key);
                    } catch (_e) { resumeId = null; }
                    var resumeExists = !!resumeId && conversations.some(function (c) { return String(c.conversation_id) === String(resumeId); });
                    var targetId = resumeExists ? resumeId : conversations[0].conversation_id;
                    ConversationManager.setActiveConversation(targetId);
                    WorkspaceManager.highlightActiveConversation(targetId);
                }
            } else {
                var currentActive = ConversationManager.getActiveConversation();
                if (currentActive) WorkspaceManager.highlightActiveConversation(currentActive);
            }

            // popstate handler
            window.onpopstate = function (event) {
                if (event.state && event.state.conversationId) {
                    ConversationManager.setActiveConversation(event.state.conversationId);
                } else {
                    var curId = ConversationManager.getActiveConversation();
                    var prevUrl = window.history.previousUrl;
                    var prevId = getConversationIdFromUrl(prevUrl);
                    if (curId !== prevId) window.history.back();
                }
            };

            // search domain auto-stateless
            if (currentDomain['domain'] === 'search') {
                var activeNode = $('#workspaces-container').jstree(true);
                if (activeNode) {
                    var sel = activeNode.get_selected();
                    if (sel && sel.length && sel[0].indexOf('cv_') === 0) {
                        var cid = sel[0].substring(3);
                        ConversationManager.statelessConversation(cid);
                    }
                }
            }
        }).fail(function () {
            console.error('Failed to load workspaces or conversations');
        });

        return $.when(workspacesRequest, conversationsRequest);
    },

    // ---------------------------------------------------------------
    // Helpers
    // ---------------------------------------------------------------
    getWorkspaceDisplayName: function (workspace) {
        if (!workspace) return '';
        if (workspace.workspace_id === this.defaultWorkspaceId) return 'General';
        return workspace.name || '';
    },

    /**
     * Build a breadcrumb path string for a workspace, e.g. "General > Private > Sub".
     * Walks up parent_workspace_id chain and reverses.
     */
    getWorkspaceBreadcrumb: function (workspaceId) {
        var parts = [];
        var visited = {};
        var currentId = workspaceId;
        while (currentId && !visited[currentId]) {
            visited[currentId] = true;
            var ws = this.workspaces[currentId];
            if (!ws) break;
            parts.push(this.getWorkspaceDisplayName(ws));
            currentId = ws.parent_workspace_id;
        }
        parts.reverse();
        return parts.join(' > ');
    },

    getWorkspaceDescendantIds: function (workspaceId) {
        var descendants = {};
        var stack = [workspaceId];
        while (stack.length) {
            var current = stack.pop();
            var wsList = Object.values(this.workspaces);
            for (var i = 0; i < wsList.length; i++) {
                if (wsList[i].parent_workspace_id === current && !descendants[wsList[i].workspace_id]) {
                    descendants[wsList[i].workspace_id] = true;
                    stack.push(wsList[i].workspace_id);
                }
            }
        }
        return descendants;
    },

    // ---------------------------------------------------------------
    // Build jsTree data array
    // ---------------------------------------------------------------
    buildJsTreeData: function (convByWs) {
        var self = this;
        var data = [];

        // Build workspace nodes (with parent pointers for jsTree)
        Object.values(this.workspaces).forEach(function (ws) {
            var displayName = self.getWorkspaceDisplayName(ws);
            var convCount = (convByWs[ws.workspace_id] || []).length;
            var parentNodeId = ws.parent_workspace_id ? ('ws_' + ws.parent_workspace_id) : '#';
            data.push({
                id: 'ws_' + ws.workspace_id,
                parent: parentNodeId,
                text: displayName + (convCount > 0 ? ' (' + convCount + ')' : ''),
                type: 'workspace',
                state: { opened: ws.expanded },
                li_attr: { 'data-workspace-id': ws.workspace_id, 'data-color': ws.color },
                a_attr: { title: displayName }
            });
        });

        // Build conversation nodes under their workspace
        Object.keys(convByWs).forEach(function (wsId) {
            var conversations = convByWs[wsId];
            conversations.forEach(function (conv) {
                var title = conv.title ? conv.title.trim() : '(untitled)';
                var flagClass = (conv.flag && conv.flag !== 'none') ? ' jstree-flag-' + conv.flag : '';
                data.push({
                    id: 'cv_' + conv.conversation_id,
                    parent: 'ws_' + wsId,
                    text: title,
                    type: 'conversation',
                    li_attr: {
                        'data-conversation-id': conv.conversation_id,
                        'data-flag': conv.flag || 'none',
                        'class': flagClass
                    },
                    a_attr: {
                        title: conv.title || '',
                        'data-conversation-id': conv.conversation_id
                    }
                });
            });
        });

        return data;
    },

    // ---------------------------------------------------------------
    // Render jsTree
    // ---------------------------------------------------------------
    renderTree: function (convByWs) {
        var self = this;
        var container = $('#workspaces-container');

        // Destroy previous instance if any
        if (this._jsTreeReady) {
            try { container.jstree('destroy'); } catch (_e) {}
            this._jsTreeReady = false;
        }

        var treeData = this.buildJsTreeData(convByWs);

        container.jstree({
            core: {
                data: treeData,
                check_callback: true,    // allow programmatic modifications
                themes: {
                    name: 'default-dark',
                    dots: false,
                    icons: true,
                    responsive: true
                },
                multiple: false
            },
            types: {
                workspace: {
                    icon: 'fa fa-folder',
                    li_attr: { 'class': 'ws-node' }
                },
                conversation: {
                    icon: 'fa fa-comment-o',
                    li_attr: { 'class': 'conv-node' },
                    max_depth: 0   // conversations cannot have children
                }
            },
            contextmenu: {
                // We handle right-click ourselves via container contextmenu.ws handler.
                // Keep the plugin loaded so $.vakata.context is available,
                // but disable its built-in trigger to avoid double-fire.
                show_at_node: false,
                select_node: false,
                items: function () { return {}; }  // empty — we build items in showNodeContextMenu
            },
            plugins: ['types', 'wholerow', 'contextmenu']
        });

        // ---- jsTree events ----

        container.off('ready.jstree').on('ready.jstree', function () {
            self._jsTreeReady = true;
            self.addTripleDotButtons();

            // Process any highlight that was queued before the tree was ready
            if (self._pendingHighlight) {
                var cid = self._pendingHighlight;
                self._pendingHighlight = null;
                self.highlightActiveConversation(cid);
            }
        });

        // Re-add triple-dot buttons when tree is redrawn (open/close)
        container.off('redraw.jstree').on('redraw.jstree', function () {
            self.addTripleDotButtons();
        });
        container.off('after_open.jstree').on('after_open.jstree', function () {
            self.addTripleDotButtons();
        });

        // Node selection → open conversation or select workspace
        container.off('select_node.jstree').on('select_node.jstree', function (e, data) {
            var nodeId = data.node.id;
            if (nodeId.indexOf('cv_') === 0) {
                var conversationId = nodeId.substring(3);
                var currentActive = (ConversationManager.getActiveConversation && ConversationManager.getActiveConversation()) || null;
                if (currentActive && String(currentActive) === String(conversationId)) return;

                // Close sidebar on mobile
                try {
                    if (window.matchMedia && window.matchMedia('(max-width: 768px)').matches) {
                        var sidebar = $('#chat-assistant-sidebar');
                        var contentCol = $('#chat-assistant');
                        if (sidebar.length && contentCol.length && !sidebar.hasClass('d-none')) {
                            sidebar.addClass('d-none');
                            contentCol.removeClass('col-md-10').addClass('col-md-12');
                            $(window).trigger('resize');
                        }
                    }
                } catch (_e) {}

                ConversationManager.setActiveConversation(conversationId);
            }
        });

        // Persist expand/collapse state to server
        container.off('open_node.jstree').on('open_node.jstree', function (e, data) {
            var nodeId = data.node.id;
            if (nodeId.indexOf('ws_') === 0) {
                var wsId = nodeId.substring(3);
                $.ajax({
                    url: '/update_workspace/' + wsId,
                    type: 'PUT',
                    contentType: 'application/json',
                    data: JSON.stringify({ expanded: true })
                });
            }
        });

        // Right-click handler — catch contextmenu on any element inside the tree.
        // Bind on the container itself to catch clicks on <li>, ocl, anchor, wholerow etc.
        container.off('contextmenu.ws').on('contextmenu.ws', function (e) {
            var $target = $(e.target);
            // Find the closest jstree-node <li>
            var $node = $target.closest('.jstree-node');
            if (!$node.length) return;

            e.preventDefault();
            e.stopPropagation();
            e.stopImmediatePropagation();

            var nodeId = $node.attr('id');
            if (nodeId) {
                self.showNodeContextMenu(nodeId, e.pageX, e.pageY);
            }
        });

        container.off('close_node.jstree').on('close_node.jstree', function (e, data) {
            var nodeId = data.node.id;
            if (nodeId.indexOf('ws_') === 0) {
                var wsId = nodeId.substring(3);
                $.ajax({
                    url: '/update_workspace/' + wsId,
                    type: 'PUT',
                    contentType: 'application/json',
                    data: JSON.stringify({ expanded: false })
                });
            }
        });
    },

    // ---------------------------------------------------------------
    // Triple-dot menu buttons on each node
    // ---------------------------------------------------------------
    addTripleDotButtons: function () {
        var self = this;
        // Add a triple-dot button after the anchor of every node
        $('#workspaces-container .jstree-node').each(function () {
            var $li = $(this);
            // Skip if already added (check sibling of anchor)
            if ($li.find('> .jstree-node-menu-btn').length) return;

            var nodeId = $li.attr('id');
            var btn = $('<span class="jstree-node-menu-btn" title="Menu"><i class="fa fa-ellipsis-v"></i></span>');

            // Insert right after the anchor (before any <ul> children)
            var anchor = $li.find('> .jstree-anchor');
            if (anchor.length) {
                anchor.after(btn);
            } else {
                // Fallback: prepend so it's at top of the <li>
                $li.prepend(btn);
            }

            btn.on('click', function (e) {
                e.preventDefault();
                e.stopPropagation();
                e.stopImmediatePropagation();
                self.showNodeContextMenu(nodeId, e.pageX, e.pageY);
                return false;
            });

            // Also prevent mousedown from bubbling to jsTree's selection handler
            btn.on('mousedown', function (e) {
                e.stopPropagation();
                e.stopImmediatePropagation();
            });
        });
    },

    showNodeContextMenu: function (nodeId, x, y) {
        var container = $('#workspaces-container');
        var tree = container.jstree(true);
        if (!tree) return;
        var node = tree.get_node(nodeId);
        if (!node) return;

        // Close any existing context menu first
        $.vakata.context.hide();

        // Build items and show via vakata context menu directly
        var items = this.buildContextMenuItems(node);
        var vakata_items = this._convertToVakataItems(items, node);

        // Position: ensure menu appears to the right of the sidebar, not behind it.
        // Use the sidebar's right edge as the minimum x position.
        var sidebar = $('#chat-assistant-sidebar');
        var sidebarRight = 0;
        if (sidebar.length) {
            var sidebarOffset = sidebar.offset();
            sidebarRight = sidebarOffset.left + sidebar.outerWidth();
        }
        var menuX = Math.max(x, sidebarRight + 2);
        var menuY = y;

        // Create a temporary positioning element at the adjusted coordinates
        var posEl = $('<span>').css({
            position: 'absolute',
            left: menuX + 'px',
            top: menuY + 'px',
            width: '1px',
            height: '1px'
        });
        $('body').append(posEl);

        $.vakata.context.show(
            posEl,
            { x: menuX, y: menuY },
            vakata_items
        );

        // Clean up positioning element after menu is shown
        setTimeout(function () { posEl.remove(); }, 200);
    },

    /**
     * Convert our jsTree contextmenu items format into vakata context format.
     * jsTree uses { label, icon, action, submenu, _disabled, separator_before, separator_after }
     * vakata uses { label, icon, action, submenu, _disabled, separator_before, separator_after }
     * They are mostly the same but vakata action receives a different signature.
     */
    _convertToVakataItems: function (items, node) {
        var self = this;
        var result = {};
        var keys = Object.keys(items);
        var nextNeedsSepBefore = false;

        keys.forEach(function (key) {
            var item = items[key];

            // Pure separator entry (no label) — mark next real item
            if (!item.label && (item.separator_after || item.separator_before)) {
                nextNeedsSepBefore = true;
                return;
            }

            var converted = {
                label: item.label,
                icon: item.icon || '',
                _disabled: item._disabled || false,
                separator_before: nextNeedsSepBefore || (item.separator_before || false),
                separator_after: item.separator_after || false
            };
            nextNeedsSepBefore = false;

            if (item.action) {
                converted.action = (function (origAction) {
                    return function () { origAction.call(self, node); };
                })(item.action);
            }
            if (item.submenu) {
                converted.submenu = self._convertToVakataItems(item.submenu, node);
            }
            result[key] = converted;
        });
        return result;
    },

    // ---------------------------------------------------------------
    // Context menu items (right-click AND triple-dot)
    // ---------------------------------------------------------------
    buildContextMenuItems: function (node) {
        var self = this;
        var nodeId = node.id;

        if (nodeId.indexOf('ws_') === 0) {
            return self.buildWorkspaceContextMenu(node);
        } else if (nodeId.indexOf('cv_') === 0) {
            return self.buildConversationContextMenu(node);
        }
        return {};
    },

    buildWorkspaceContextMenu: function (node) {
        var self = this;
        var wsId = node.id.substring(3);
        var isDefault = (wsId === this.defaultWorkspaceId);

        var items = {
            addConversation: {
                label: 'New Conversation',
                icon: 'fa fa-file-o',
                action: function () { self.createConversationInWorkspace(wsId); }
            },
            addSubWorkspace: {
                label: 'New Sub-Workspace',
                icon: 'fa fa-folder-o',
                action: function () { self.showCreateWorkspaceModal(wsId); }
            },
            rename: {
                separator_before: true,
                label: 'Rename',
                icon: 'fa fa-edit',
                _disabled: isDefault,
                action: function () { self.showRenameWorkspaceModal(wsId); }
            },
            changeColor: {
                label: 'Change Color',
                icon: 'fa fa-palette',
                action: function () { self.showWorkspaceColorModal(wsId); }
            },
            moveTo: {
                label: 'Move to...',
                icon: 'fa fa-folder-open',
                _disabled: isDefault,
                submenu: self.buildWorkspaceMoveSubmenu(wsId)
            },
            deleteWs: {
                separator_before: true,
                label: 'Delete',
                icon: 'fa fa-trash',
                _disabled: isDefault,
                action: function () { self.deleteWorkspace(wsId); }
            }
        };
        return items;
    },

    buildConversationContextMenu: function (node) {
        var self = this;
        var convId = node.id.substring(3);

        var items = {
            openNewWindow: {
                label: 'Open in New Window',
                icon: 'fa fa-external-link',
                action: function () {
                    window.open('/interface/' + convId, '_blank', 'noopener');
                }
            },
            clone: {
                separator_before: true,
                label: 'Clone',
                icon: 'fa fa-clone',
                action: function () {
                    ConversationManager.cloneConversation(convId).done(function (cloned) {
                        self.loadConversationsWithWorkspaces(false).done(function () {
                            ConversationManager.setActiveConversation(cloned.conversation_id);
                            self.highlightActiveConversation(cloned.conversation_id);
                        });
                    });
                }
            },
            toggleStateless: {
                label: 'Toggle Stateless',
                icon: 'fa fa-eye-slash',
                action: function () {
                    // Determine current state from conversation data
                    ConversationManager.statelessConversation(convId);
                }
            },
            flag: {
                label: 'Set Flag',
                icon: 'fa fa-flag',
                submenu: self.buildFlagSubmenu(convId)
            },
            moveTo: {
                label: 'Move to...',
                icon: 'fa fa-folder-open',
                submenu: self.buildConversationMoveSubmenu(convId)
            },
            deleteConv: {
                separator_before: true,
                label: 'Delete',
                icon: 'fa fa-trash',
                action: function () {
                    $.ajax({
                        url: '/delete_conversation/' + convId,
                        type: 'DELETE',
                        success: function () {
                            self.loadConversationsWithWorkspaces(false).done(function () {
                                if (ConversationManager.activeConversationId === convId) {
                                    if (self.conversations.length > 0) {
                                        var nextId = self.conversations[0].conversation_id;
                                        ConversationManager.setActiveConversation(nextId);
                                        self.highlightActiveConversation(nextId);
                                    }
                                }
                            });
                        }
                    });
                }
            }
        };
        return items;
    },

    buildFlagSubmenu: function (convId) {
        var self = this;
        var flags = {
            none: { label: 'No Flag', icon: 'fa fa-flag-o' },
            red: { label: 'Red', icon: 'fa fa-flag' },
            blue: { label: 'Blue', icon: 'fa fa-flag' },
            green: { label: 'Green', icon: 'fa fa-flag' },
            yellow: { label: 'Yellow', icon: 'fa fa-flag' },
            orange: { label: 'Orange', icon: 'fa fa-flag' },
            purple: { label: 'Purple', icon: 'fa fa-flag' }
        };
        var submenu = {};
        Object.keys(flags).forEach(function (color) {
            submenu['flag_' + color] = {
                label: flags[color].label,
                icon: flags[color].icon,
                action: function () {
                    $.ajax({
                        url: '/set_flag/' + convId + '/' + color,
                        type: 'POST',
                        success: function () {
                            self.loadConversationsWithWorkspaces(false);
                        }
                    });
                }
            };
        });
        return submenu;
    },

    buildConversationMoveSubmenu: function (convId) {
        var self = this;
        var submenu = {};
        // Flatten all workspaces and show full breadcrumb path for each
        Object.values(this.workspaces).forEach(function (ws) {
            var breadcrumb = self.getWorkspaceBreadcrumb(ws.workspace_id);
            submenu['move_' + ws.workspace_id] = {
                label: breadcrumb,
                icon: 'fa fa-folder',
                action: function () {
                    self.moveConversationToWorkspace(convId, ws.workspace_id);
                }
            };
        });
        return submenu;
    },

    buildWorkspaceMoveSubmenu: function (wsId) {
        var self = this;
        var descendants = this.getWorkspaceDescendantIds(wsId);
        descendants[wsId] = true;
        var currentWs = this.workspaces[wsId];
        var currentParent = currentWs ? currentWs.parent_workspace_id : null;

        var submenu = {};

        // "Top level" option
        submenu['move_root'] = {
            label: 'Top level (root)',
            icon: 'fa fa-arrow-up',
            _disabled: !currentParent,
            action: function () { self.moveWorkspaceToParent(wsId, null); }
        };

        // Flatten all workspaces with full breadcrumb path
        Object.values(this.workspaces).forEach(function (ws) {
            var isDisabled = !!descendants[ws.workspace_id];
            var isCurrent = (ws.workspace_id === (currentParent || ''));
            var breadcrumb = self.getWorkspaceBreadcrumb(ws.workspace_id);
            submenu['move_ws_' + ws.workspace_id] = {
                label: breadcrumb,
                icon: 'fa fa-folder',
                _disabled: isDisabled || isCurrent,
                action: function () { self.moveWorkspaceToParent(wsId, ws.workspace_id); }
            };
        });
        return submenu;
    },

    // ---------------------------------------------------------------
    // CRUD operations
    // ---------------------------------------------------------------
    createWorkspace: function (name, color, parentWorkspaceId) {
        color = color || 'primary';
        parentWorkspaceId = parentWorkspaceId || null;
        var self = this;
        return $.ajax({
            url: '/create_workspace/' + currentDomain['domain'] + '/' + encodeURIComponent(name),
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ workspace_color: color, parent_workspace_id: parentWorkspaceId }),
            success: function () { self.loadConversationsWithWorkspaces(false); }
        });
    },

    renameWorkspace: function (workspaceId, newName) {
        var self = this;
        return $.ajax({
            url: '/update_workspace/' + workspaceId,
            type: 'PUT',
            contentType: 'application/json',
            data: JSON.stringify({ workspace_name: newName }),
            success: function () { self.loadConversationsWithWorkspaces(false); }
        });
    },

    updateWorkspaceColor: function (workspaceId, newColor) {
        var self = this;
        return $.ajax({
            url: '/update_workspace/' + workspaceId,
            type: 'PUT',
            contentType: 'application/json',
            data: JSON.stringify({ workspace_color: newColor }),
            success: function () { self.loadConversationsWithWorkspaces(false); }
        });
    },

    deleteWorkspace: function (workspaceId) {
        if (workspaceId === this.defaultWorkspaceId) {
            alert('Cannot delete the default workspace');
            return;
        }
        var self = this;
        if (confirm('Delete this workspace? Children and conversations will be moved to the parent (or General).')) {
            return $.ajax({
                url: '/delete_workspace/' + currentDomain['domain'] + '/' + workspaceId,
                type: 'DELETE',
                success: function () { self.loadConversationsWithWorkspaces(false); }
            });
        }
    },

    moveConversationToWorkspace: function (conversationId, targetWorkspaceId) {
        var self = this;
        return $.ajax({
            url: '/move_conversation_to_workspace/' + conversationId,
            type: 'PUT',
            contentType: 'application/json',
            data: JSON.stringify({ workspace_id: targetWorkspaceId }),
            success: function () {
                var currentActive = ConversationManager.getActiveConversation();
                self.loadConversationsWithWorkspaces(false).done(function () {
                    if (currentActive) {
                        setTimeout(function () { self.highlightActiveConversation(currentActive); }, 100);
                    }
                });
            },
            error: function () { alert('Failed to move conversation.'); }
        });
    },

    moveWorkspaceToParent: function (workspaceId, parentWorkspaceId) {
        var self = this;
        return $.ajax({
            url: '/move_workspace/' + workspaceId,
            type: 'PUT',
            contentType: 'application/json',
            data: JSON.stringify({ parent_workspace_id: parentWorkspaceId }),
            success: function () { self.loadConversationsWithWorkspaces(false); },
            error: function () { alert('Failed to move workspace.'); }
        });
    },

    createConversationInWorkspace: function (workspaceId) {
        var self = this;
        $.ajax({
            url: '/create_conversation/' + currentDomain['domain'] + '/' + workspaceId,
            type: 'POST',
            success: function (conversation) {
                $('#linkInput').val('');
                $('#searchInput').val('');
                self.loadConversationsWithWorkspaces(true).done(function () {
                    ConversationManager.setActiveConversation(conversation.conversation_id);
                    self.highlightActiveConversation(conversation.conversation_id);
                });
            }
        });
    },

    // ---------------------------------------------------------------
    // Highlighting
    // ---------------------------------------------------------------
    highlightActiveConversation: function (conversationId) {
        // If tree isn't ready yet, queue for later
        if (!this._jsTreeReady) {
            this._pendingHighlight = conversationId;
            return;
        }

        var tree = $('#workspaces-container').jstree(true);
        if (!tree) {
            this._pendingHighlight = conversationId;
            return;
        }

        // Deselect everything, then select the conversation node
        tree.deselect_all(true);
        var nodeId = 'cv_' + conversationId;
        var node = tree.get_node(nodeId);
        if (node) {
            // Open all parent nodes first so the conversation is visible
            var parentIds = [];
            var current = node;
            while (current && current.parent && current.parent !== '#') {
                parentIds.push(current.parent);
                current = tree.get_node(current.parent);
            }
            // Open from root down
            parentIds.reverse();
            parentIds.forEach(function (pid) { tree.open_node(pid, false, false); });

            // Select after parents are opened
            tree.select_node(nodeId, true);  // suppress event
        }
    },

    // ---------------------------------------------------------------
    // Modal dialogs (create workspace, rename, color)
    // ---------------------------------------------------------------
    showCreateWorkspaceModal: function (parentWorkspaceId) {
        parentWorkspaceId = parentWorkspaceId || null;
        var self = this;
        var modalTitle = parentWorkspaceId ? 'Create Sub-Workspace' : 'Create New Workspace';

        var modal = $([
            '<div class="modal fade" id="create-workspace-modal" tabindex="-1">',
            '  <div class="modal-dialog">',
            '    <div class="modal-content">',
            '      <div class="modal-header">',
            '        <h5 class="modal-title">' + modalTitle + '</h5>',
            '        <button type="button" class="close" data-dismiss="modal"><span>&times;</span></button>',
            '      </div>',
            '      <div class="modal-body">',
            '        <div class="mb-3">',
            '          <label class="form-label">Workspace Name</label>',
            '          <input type="text" class="form-control" id="workspace-name" placeholder="Enter name">',
            '        </div>',
            '        <div class="mb-3">',
            '          <label class="form-label">Color</label>',
            '          <select class="custom-select" id="workspace-color">',
            '            <option value="primary">Blue</option>',
            '            <option value="success">Green</option>',
            '            <option value="danger">Red</option>',
            '            <option value="warning">Yellow</option>',
            '            <option value="info">Cyan</option>',
            '            <option value="purple">Purple</option>',
            '            <option value="pink">Pink</option>',
            '            <option value="orange">Orange</option>',
            '          </select>',
            '        </div>',
            '      </div>',
            '      <div class="modal-footer">',
            '        <button type="button" class="btn btn-secondary" data-dismiss="modal">Cancel</button>',
            '        <button type="button" class="btn btn-primary" id="create-workspace-btn">Create</button>',
            '      </div>',
            '    </div>',
            '  </div>',
            '</div>'
        ].join('\n'));

        $('body').append(modal);
        modal.modal('show');

        $('#create-workspace-btn').on('click', function () {
            var name = $('#workspace-name').val().trim();
            var color = $('#workspace-color').val();
            if (name) { self.createWorkspace(name, color, parentWorkspaceId); modal.modal('hide'); }
        });
        modal.on('hidden.bs.modal', function () { modal.remove(); });
    },

    showRenameWorkspaceModal: function (workspaceId) {
        var self = this;
        var ws = this.workspaces[workspaceId];
        if (!ws) return;

        var modal = $([
            '<div class="modal fade" id="rename-workspace-modal" tabindex="-1">',
            '  <div class="modal-dialog">',
            '    <div class="modal-content">',
            '      <div class="modal-header">',
            '        <h5 class="modal-title">Rename Workspace</h5>',
            '        <button type="button" class="close" data-dismiss="modal"><span>&times;</span></button>',
            '      </div>',
            '      <div class="modal-body">',
            '        <input type="text" class="form-control" id="workspace-rename" value="' + (ws.name || '') + '">',
            '      </div>',
            '      <div class="modal-footer">',
            '        <button type="button" class="btn btn-secondary" data-dismiss="modal">Cancel</button>',
            '        <button type="button" class="btn btn-primary" id="rename-workspace-btn">Rename</button>',
            '      </div>',
            '    </div>',
            '  </div>',
            '</div>'
        ].join('\n'));

        $('body').append(modal);
        modal.modal('show');
        $('#rename-workspace-btn').on('click', function () {
            var newName = $('#workspace-rename').val().trim();
            if (newName && newName !== ws.name) { self.renameWorkspace(workspaceId, newName); modal.modal('hide'); }
        });
        modal.on('hidden.bs.modal', function () { modal.remove(); });
    },

    showWorkspaceColorModal: function (workspaceId) {
        var self = this;
        var ws = this.workspaces[workspaceId];
        if (!ws) return;

        var options = ['primary', 'success', 'danger', 'warning', 'info', 'purple', 'pink', 'orange'];
        var labels = { primary: 'Blue', success: 'Green', danger: 'Red', warning: 'Yellow', info: 'Cyan', purple: 'Purple', pink: 'Pink', orange: 'Orange' };
        var optionsHtml = options.map(function (c) {
            return '<option value="' + c + '"' + (ws.color === c ? ' selected' : '') + '>' + labels[c] + '</option>';
        }).join('');

        var modal = $([
            '<div class="modal fade" id="color-workspace-modal" tabindex="-1">',
            '  <div class="modal-dialog">',
            '    <div class="modal-content">',
            '      <div class="modal-header">',
            '        <h5 class="modal-title">Change Workspace Color</h5>',
            '        <button type="button" class="close" data-dismiss="modal"><span>&times;</span></button>',
            '      </div>',
            '      <div class="modal-body">',
            '        <select class="custom-select" id="workspace-color-change">' + optionsHtml + '</select>',
            '      </div>',
            '      <div class="modal-footer">',
            '        <button type="button" class="btn btn-secondary" data-dismiss="modal">Cancel</button>',
            '        <button type="button" class="btn btn-primary" id="color-workspace-btn">Change</button>',
            '      </div>',
            '    </div>',
            '  </div>',
            '</div>'
        ].join('\n'));

        $('body').append(modal);
        modal.modal('show');
        $('#color-workspace-btn').on('click', function () {
            var newColor = $('#workspace-color-change').val();
            if (newColor !== ws.color) { self.updateWorkspaceColor(workspaceId, newColor); modal.modal('hide'); }
        });
        modal.on('hidden.bs.modal', function () { modal.remove(); });
    }
};

// Initialize when document is ready
$(document).ready(function () {
    WorkspaceManager.init();
});
