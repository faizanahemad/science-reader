/**
 * WorkspaceTree — jsTree-based sidebar for hierarchical workspace/conversation browsing.
 *
 * Replaces the flat conversation list with a tree grouped by workspaces.
 * Uses emoji icons (no FontAwesome) for CSP safety in Chrome extensions.
 *
 * Node conventions:
 *   - workspace nodes:   id = "ws_<workspace_id>",  type = "workspace"
 *   - conversation nodes: id = "cv_<conversation_id>", type = "conversation"
 */

import { API } from '../shared/api.js';
import { Storage } from '../shared/storage.js';
import { API_BASE } from '../shared/constants.js';

var EXTENSION_WORKSPACE_NAME = 'Browser Extension';
var EXTENSION_WORKSPACE_COLOR = '#9b59b6';

var WorkspaceTree = {
    _ready: false,
    _pendingHighlight: null,

    init: function () {
        this._renderTree([]);
    },

    _renderTree: function (treeData) {
        var self = this;
        var container = $('#workspace-tree');
        if (!container.length) return;

        if ($.jstree.reference(container)) {
            try { container.jstree('destroy'); } catch (_e) {}
            this._ready = false;
        }

        container.jstree({
            core: {
                data: treeData,
                themes: { name: 'default-dark', dots: false, icons: true },
                check_callback: true,
                multiple: false
            },
            types: {
                workspace: { icon: '📁' },
                conversation: { icon: '💬' }
            },
            plugins: ['types', 'wholerow', 'contextmenu', 'sort'],
            contextmenu: {
                show_at_node: false,
                select_node: false,
                items: function () { return {}; }
            },
            sort: function (a, b) {
                var nodeA = this.get_node(a);
                var nodeB = this.get_node(b);
                var typeA = (nodeA && nodeA.type === 'workspace') ? 0 : 1;
                var typeB = (nodeB && nodeB.type === 'workspace') ? 0 : 1;
                if (typeA !== typeB) return typeA - typeB;
                return 0;
            }
        });

        container.off('ready.jstree').on('ready.jstree', function () {
            self._ready = true;
            self._addTripleDotButtons();
            if (self._pendingHighlight) {
                self.highlightConversation(self._pendingHighlight);
                self._pendingHighlight = null;
            }
        });

        container.off('redraw.jstree after_open.jstree').on('redraw.jstree after_open.jstree', function () {
            self._addTripleDotButtons();
        });

        container.off('contextmenu.ws').on('contextmenu.ws', function (e) {
            var $node = $(e.target).closest('.jstree-node');
            if (!$node.length) return;
            e.preventDefault();
            e.stopPropagation();
            e.stopImmediatePropagation();
            var nodeId = $node.attr('id');
            if (nodeId) {
                self._showNodeContextMenu(nodeId, e.pageX, e.pageY);
            }
        });

        container.off('select_node.jstree').on('select_node.jstree', function (e, data) {
            var nodeId = data.node.id;
            if (nodeId.indexOf('ws_') === 0) {
                var tree = container.jstree(true);
                if (tree) {
                    tree.toggle_node(data.node);
                    tree.deselect_node(data.node, true);
                }
                return;
            }
            if (nodeId.indexOf('cv_') === 0) {
                var conversationId = nodeId.substring(3);
                document.dispatchEvent(new CustomEvent('conversation-selected', {
                    detail: { conversationId: conversationId }
                }));
            }
        });
    },

    /**
     * Compute the default workspace ID for a user+domain, matching the main UI
     * convention: "default_<email>_<domain>".
     */
    _computeDefaultWorkspaceId: async function (domain) {
        var userInfo = await Storage.getUserInfo();
        var email = (userInfo && userInfo.email) ? userInfo.email : 'unknown';
        var dom = domain || 'unknown';
        return 'default_' + email + '_' + dom;
    },

    loadTree: async function (domain) {
        var workspaces = [];
        var conversations = [];

        // Compute defaultWorkspaceId so we can display "General" for the default workspace
        this._defaultWorkspaceId = await this._computeDefaultWorkspaceId(domain);

        try {
            workspaces = await API.listWorkspaces(domain);
        } catch (e) {
            console.warn('[WorkspaceTree] Failed to load workspaces:', e);
        }

        try {
            conversations = await API.getConversations();
            if (!Array.isArray(conversations)) conversations = [];
        } catch (e) {
            console.warn('[WorkspaceTree] Failed to load conversations:', e);
        }

        var extWs = workspaces.find(function (ws) {
            return ws.workspace_name === EXTENSION_WORKSPACE_NAME;
        });
        if (!extWs) {
            try {
                var created = await API.createWorkspace(domain, EXTENSION_WORKSPACE_NAME, {
                    color: EXTENSION_WORKSPACE_COLOR
                });
                extWs = { workspace_id: created.workspace_id, workspace_name: EXTENSION_WORKSPACE_NAME };
                workspaces.push(extWs);
            } catch (e) {
                console.warn('[WorkspaceTree] Failed to create extension workspace:', e);
            }
        }

        var treeData = this._buildTreeData(workspaces, conversations, extWs);
        this._setTreeData(treeData);
        this._workspaces = workspaces;

        var emptyEl = document.getElementById('conversation-empty');
        if (emptyEl) {
            emptyEl.classList.toggle('hidden', conversations.length > 0);
        }

        return { workspaces: workspaces, conversations: conversations, extensionWorkspace: extWs };
    },

    refreshTree: async function () {
        var domain = await Storage.getDomain();
        return this.loadTree(domain);
    },

    addConversationNode: function (conversation, workspaceId) {
        var tree = $('#workspace-tree').jstree(true);
        if (!tree) return;

        var parentId = workspaceId ? ('ws_' + workspaceId) : '#';
        if (workspaceId && !tree.get_node(parentId)) {
            parentId = '#';
        }

        var nodeId = 'cv_' + conversation.conversation_id;
        if (tree.get_node(nodeId)) return;

        tree.create_node(parentId, {
            id: nodeId,
            text: conversation.title || 'New Chat',
            type: 'conversation',
            li_attr: {
                'data-conversation-id': conversation.conversation_id,
                'data-conversation-friendly-id': conversation.friendly_id || ''
            }
        });

        if (parentId !== '#') {
            tree.open_node(parentId);
        }
    },

    removeConversationNode: function (conversationId) {
        var tree = $('#workspace-tree').jstree(true);
        if (!tree) return;
        var nodeId = 'cv_' + conversationId;
        if (tree.get_node(nodeId)) {
            tree.delete_node(nodeId);
        }
    },

    highlightConversation: function (conversationId) {
        if (!this._ready) {
            this._pendingHighlight = conversationId;
            return;
        }
        var tree = $('#workspace-tree').jstree(true);
        if (!tree) return;

        var nodeId = 'cv_' + conversationId;
        var node = tree.get_node(nodeId);
        if (!node) {
            this._pendingHighlight = conversationId;
            return;
        }

        this._pendingHighlight = null;
        if (node.parent && node.parent !== '#') {
            tree.open_node(node.parent);
        }
        tree.deselect_all(true);
        tree.select_node(nodeId, true);
    },

    getSelectedConversationId: function () {
        var tree = $('#workspace-tree').jstree(true);
        if (!tree) return null;
        var sel = tree.get_selected();
        if (!sel || !sel.length) return null;
        var nodeId = sel[0];
        if (nodeId.indexOf('cv_') === 0) return nodeId.substring(3);
        return null;
    },

    updateConversationTitle: function (conversationId, newTitle) {
        var tree = $('#workspace-tree').jstree(true);
        if (!tree) return;
        var nodeId = 'cv_' + conversationId;
        if (tree.get_node(nodeId)) {
            tree.rename_node(nodeId, newTitle);
        }
    },

    _buildTreeData: function (workspaces, conversations, extWs) {
        var data = [];
        var wsMap = {};

        var defaultWsId = this._defaultWorkspaceId || null;

        workspaces.forEach(function (ws) {
            wsMap[ws.workspace_id] = ws;
            var convCount = conversations.filter(function (c) {
                return c.workspace_id === ws.workspace_id;
            }).length;
            var displayName = (ws.workspace_id === defaultWsId) ? 'General' : ws.workspace_name;
            var label = displayName + (convCount > 0 ? ' (' + convCount + ')' : '');

            var parentNodeId = ws.parent_workspace_id ? ('ws_' + ws.parent_workspace_id) : '#';
            data.push({
                id: 'ws_' + ws.workspace_id,
                parent: parentNodeId,
                text: label,
                type: 'workspace',
                state: {
                    opened: ws.workspace_name === EXTENSION_WORKSPACE_NAME
                },
                li_attr: { 'data-workspace-id': ws.workspace_id }
            });
        });

        var fallbackWsId = extWs ? extWs.workspace_id : null;

        conversations.forEach(function (conv) {
            var wsId = conv.workspace_id;
            if (!wsId || !wsMap[wsId]) {
                wsId = fallbackWsId;
            }
            var parentId = wsId ? ('ws_' + wsId) : '#';
            var flagClass = (conv.flag && conv.flag !== 'none') ? 'jstree-flag-' + conv.flag : '';

            data.push({
                id: 'cv_' + conv.conversation_id,
                parent: parentId,
                text: conv.title || 'New Chat',
                type: 'conversation',
                li_attr: {
                    'data-conversation-id': conv.conversation_id,
                    'data-conversation-friendly-id': conv.conversation_friendly_id || conv.friendly_id || '',
                    'data-flag': conv.flag || 'none',
                    'class': flagClass
                }
            });
        });

        return data;
    },

    _setTreeData: function (treeData) {
        this._renderTree(treeData);
    },

    _contextMenuItems: function (node) {
        var self = this;
        if (node.type === 'workspace') {
            return {
                newChat: {
                    label: '+ New Chat',
                    action: function () {
                        var wsId = node.id.substring(3);
                        document.dispatchEvent(new CustomEvent('tree-new-chat', {
                            detail: { workspaceId: wsId, temporary: false }
                        }));
                    }
                },
                quickChat: {
                    label: '\u26a1 Quick Chat',
                    action: function () {
                        var wsId = node.id.substring(3);
                        document.dispatchEvent(new CustomEvent('tree-new-chat', {
                            detail: { workspaceId: wsId, temporary: true }
                        }));
                    }
                }
            };
        }

        if (node.type === 'conversation') {
            var convId = node.id.substring(3);
            return {
                copyRef: {
                    label: '\ud83d\udccb Copy Reference',
                    action: function () {
                        var fid = node.li_attr['data-conversation-friendly-id'];
                        if (fid) {
                            navigator.clipboard.writeText(fid).then(function () {
                                document.dispatchEvent(new CustomEvent('tree-toast', {
                                    detail: { message: 'Copied: ' + fid, type: 'info' }
                                }));
                            });
                        }
                    },
                    _disabled: !node.li_attr['data-conversation-friendly-id'],
                    separator_after: true
                },
                openNewWindow: {
                    label: '\ud83d\udd17 Open in New Window',
                    action: async function () {
                        var base = await Storage.getApiBaseUrl();
                        base = (base || API_BASE).replace(/\/+$/, '');
                        window.open(base + '/interface/' + convId, '_blank');
                    }
                },
                clone: {
                    separator_before: true,
                    label: '\ud83d\udcd1 Clone',
                    action: function () {
                        document.dispatchEvent(new CustomEvent('tree-clone-conversation', {
                            detail: { conversationId: convId }
                        }));
                    }
                },
                toggleStateless: {
                    label: '\ud83d\udc41\ufe0f Toggle Stateless',
                    action: function () {
                        document.dispatchEvent(new CustomEvent('tree-toggle-stateless', {
                            detail: { conversationId: convId }
                        }));
                    }
                },
                flag: {
                    label: '\ud83c\udff3\ufe0f Set Flag',
                    submenu: self._buildFlagSubmenu(convId)
                },
                moveTo: {
                    label: '\ud83d\udcc1 Move to...',
                    submenu: self._buildMoveSubmenu(convId)
                },
                save: {
                    separator_before: true,
                    label: '\ud83d\udcbe Save',
                    action: function () {
                        document.dispatchEvent(new CustomEvent('tree-save-conversation', {
                            detail: { conversationId: convId }
                        }));
                    }
                },
                deleteConv: {
                    label: '\ud83d\uddd1\ufe0f Delete',
                    action: function () {
                        document.dispatchEvent(new CustomEvent('tree-delete-conversation', {
                            detail: { conversationId: convId }
                        }));
                    }
                }
            };
        }

        return {};
    },

    _buildFlagSubmenu: function (convId) {
        var flags = {
            none: '\u26aa No Flag', red: '\ud83d\udd34 Red', blue: '\ud83d\udd35 Blue',
            green: '\ud83d\udfe2 Green', yellow: '\ud83d\udfe1 Yellow', orange: '\ud83d\udfe0 Orange', purple: '\ud83d\udfe3 Purple'
        };
        var submenu = {};
        Object.keys(flags).forEach(function (color) {
            submenu['flag_' + color] = {
                label: flags[color],
                action: function () {
                    document.dispatchEvent(new CustomEvent('tree-set-flag', {
                        detail: { conversationId: convId, flag: color }
                    }));
                }
            };
        });
        return submenu;
    },

    _getWorkspaceBreadcrumb: function (workspaceId) {
        var wsMap = {};
        var defaultWsId = this._defaultWorkspaceId || null;
        (this._workspaces || []).forEach(function (ws) {
            wsMap[ws.workspace_id] = ws;
        });
        var parts = [];
        var visited = {};
        var currentId = workspaceId;
        while (currentId && !visited[currentId]) {
            visited[currentId] = true;
            var ws = wsMap[currentId];
            if (!ws) break;
            var name = (ws.workspace_id === defaultWsId) ? 'General' : ws.workspace_name;
            parts.push(name);
            currentId = ws.parent_workspace_id;
        }
        parts.reverse();
        return parts.join(' > ');
    },

    _buildMoveSubmenu: function (convId) {
        var self = this;
        var submenu = {};
        (this._workspaces || []).forEach(function (ws) {
            var breadcrumb = self._getWorkspaceBreadcrumb(ws.workspace_id);
            submenu['move_' + ws.workspace_id] = {
                label: '\ud83d\udcc1 ' + breadcrumb,
                action: function () {
                    document.dispatchEvent(new CustomEvent('tree-move-conversation', {
                        detail: { conversationId: convId, targetWorkspaceId: ws.workspace_id }
                    }));
                }
            };
        });
        return submenu;
    },

    _addTripleDotButtons: function () {
        var self = this;
        $('#workspace-tree .jstree-node').each(function () {
            var $li = $(this);
            if ($li.find('> .jstree-node-menu-btn').length) return;

            var nodeId = $li.attr('id');
            var btn = $('<span class="jstree-node-menu-btn" title="Menu">\u22ee</span>');

            var anchor = $li.find('> .jstree-anchor');
            if (anchor.length) {
                anchor.after(btn);
            } else {
                $li.prepend(btn);
            }

            btn.on('click', function (e) {
                e.preventDefault();
                e.stopPropagation();
                e.stopImmediatePropagation();
                self._showNodeContextMenu(nodeId, e.pageX, e.pageY);
                return false;
            });

            btn.on('mousedown', function (e) {
                e.stopPropagation();
                e.stopImmediatePropagation();
            });
        });
    },

    _showNodeContextMenu: function (nodeId, x, y) {
        var tree = $('#workspace-tree').jstree(true);
        if (!tree) return;
        var node = tree.get_node(nodeId);
        if (!node) return;

        $.vakata.context.hide();

        var items = this._contextMenuItems(node);
        var vakataItems = this._convertToVakataItems(items, node);

        var posEl = $('<span>').css({
            position: 'absolute',
            left: x + 'px',
            top: y + 'px',
            width: '1px',
            height: '1px'
        });
        $('body').append(posEl);

        $.vakata.context.show(posEl, { x: x, y: y }, vakataItems);

        setTimeout(function () { posEl.remove(); }, 200);
    },

    _convertToVakataItems: function (items, node) {
        var self = this;
        var result = {};
        var nextNeedsSepBefore = false;

        Object.keys(items).forEach(function (key) {
            var item = items[key];

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

    getSelectedWorkspaceId: function () {
        var tree = $('#workspace-tree').jstree(true);
        if (!tree) return null;
        var sel = tree.get_selected();
        if (!sel || !sel.length) return null;
        var nodeId = sel[0];
        if (nodeId.indexOf('cv_') === 0) {
            var node = tree.get_node(nodeId);
            if (node && node.parent && node.parent.indexOf('ws_') === 0) {
                return node.parent.substring(3);
            }
        }
        if (nodeId.indexOf('ws_') === 0) {
            return nodeId.substring(3);
        }
        return null;
    },

    openWorkspace: function (workspaceId) {
        var tree = $('#workspace-tree').jstree(true);
        if (!tree) return;
        var nodeId = 'ws_' + workspaceId;
        var node = tree.get_node(nodeId);
        if (node) {
            tree.open_node(node);
        }
    }
};

export { WorkspaceTree };
