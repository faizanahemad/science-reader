/* eslint-disable no-undef */
/**
 * TabManager — multi-conversation tab management.
 * Tracks open tabs, focused tab, persistence, and renders tab bar (desktop) / gear items (mobile).
 *
 * Up to MAX_TABS conversations can be open simultaneously.
 * Desktop: each tab gets its own DOM pane (#chatView-{convId}) inside #chatView-container; switching is instant.
 * Mobile: single shared #chatView; switching saves via RenderedStateManager then reloads via setActiveConversation.
 */
(function () {
    "use strict";

    var MAX_TABS = 5;

    function isMobileLayout() {
        try {
            return window.matchMedia('(max-width: 768px) and (pointer: coarse) and (max-height: 768px)').matches;
        } catch (_e) { return false; }
    }

    function storageKey() {
        var email = (typeof userDetails !== 'undefined' && userDetails.email) ? userDetails.email : 'unknown';
        var domain = (typeof currentDomain !== 'undefined' && currentDomain.domain) ? currentDomain.domain : 'unknown';
        return 'openTabs:' + email + ':' + domain;
    }

    var TabManager = {
        tabs: [],           // [{conversationId, title}]
        focusedTabId: null, // conversationId of visible tab
        streamControllers: {}, // {conversationId: {reader, cancel(), conversationId}}
        streamBuffers: {},  // {conversationId: [chunks]} — mobile only

        // ---------------------------------------------------------------
        // Core state
        // ---------------------------------------------------------------

        getTab: function (convId) {
            for (var i = 0; i < this.tabs.length; i++) {
                if (this.tabs[i].conversationId === convId) return this.tabs[i];
            }
            return null;
        },

        hasTab: function (convId) { return this.getTab(convId) !== null; },

        // ---------------------------------------------------------------
        // Open / Close / Focus
        // ---------------------------------------------------------------

        openTab: function (conversationId, title, shouldFocus) {
            if (!conversationId) return;
            if (this.tabs.length >= MAX_TABS && !this.hasTab(conversationId)) {
                if (typeof showToast === 'function') showToast('Maximum ' + MAX_TABS + ' tabs allowed. Close a tab first.', 'warning');
                return false;
            }
            if (!this.hasTab(conversationId)) {
                this.tabs.push({ conversationId: conversationId, title: title || 'Untitled' });
            } else if (title) {
                this.getTab(conversationId).title = title;
            }
            if (shouldFocus !== false) this.focusTab(conversationId);
            else this.renderUI();
            this.persist();
            return true;
        },

        closeTab: function (conversationId) {
            if (this.tabs.length <= 1) return; // can't close last tab
            // Mid-stream warning
            if (this.streamControllers[conversationId]) {
                if (!confirm('Response in progress, close anyway?')) return;
                this.streamControllers[conversationId].cancel();
                delete this.streamControllers[conversationId];
            }
            var idx = -1;
            for (var i = 0; i < this.tabs.length; i++) {
                if (this.tabs[i].conversationId === conversationId) { idx = i; break; }
            }
            if (idx === -1) return;
            this.tabs.splice(idx, 1);
            // Remove pane on desktop
            if (!isMobileLayout()) {
                var paneEl = document.getElementById('chatView-' + conversationId);
                if (paneEl) paneEl.parentNode.removeChild(paneEl);
            }
            delete this.streamBuffers[conversationId];
            // If closed tab was focused, focus adjacent
            if (this.focusedTabId === conversationId) {
                var newIdx = Math.min(idx, this.tabs.length - 1);
                this.focusTab(this.tabs[newIdx].conversationId);
            } else {
                this.renderUI();
            }
            this.persist();
        },

        focusTab: function (conversationId) {
            if (!conversationId) return;
            if (this.focusedTabId === conversationId) return;
            var oldId = this.focusedTabId;
            this.focusedTabId = conversationId;

            if (isMobileLayout()) {
                // Mobile: save old, then use setActiveConversation for full restore
                if (oldId && window.RenderedStateManager && window.RenderedStateManager.saveNow) {
                    try { window.RenderedStateManager.saveNow(oldId); } catch (_e) {}
                }
                if (typeof ConversationManager !== 'undefined') {
                    ConversationManager.setActiveConversation(conversationId);
                }
                // Render buffered content if any
                this._renderBuffer(conversationId);
            } else {
                // Desktop: show/hide panes via active class
                $('.chatView-pane').removeClass('active');
                var paneEl = document.getElementById('chatView-' + conversationId);
                if (paneEl) {
                    $(paneEl).addClass('active');
                } else {
                    // First time opening this tab on desktop — create pane and load
                    this._createPane(conversationId).addClass('active');
                    if (typeof ConversationManager !== 'undefined') {
                        ConversationManager.activeConversationId = conversationId;
                        ConversationManager.setActiveConversation(conversationId);
                    }
                }
                // Sync activeConversationId
                if (typeof ConversationManager !== 'undefined') {
                    ConversationManager.activeConversationId = conversationId;
                }
                // Update URL
                if (typeof updateUrlWithConversationId === 'function') {
                    updateUrlWithConversationId(conversationId);
                }
            }
            // Update send/stop button state for focused tab
            this._syncStreamUI(conversationId);
            this.renderUI();
            this.persist();
            // Highlight in sidebar
            if (typeof WorkspaceManager !== 'undefined' && WorkspaceManager.highlightActiveConversation) {
                WorkspaceManager.highlightActiveConversation(conversationId);
            }
        },

        _createPane: function (conversationId) {
            var $container = $('#chatView-container');
            if (!$container.length) return $();
            var $pane = $('<div></div>')
                .attr('id', 'chatView-' + conversationId)
                .addClass('chatView-pane row flex-grow-1 overflow-auto')
                .appendTo($container);
            return $pane;
        },

        _renderBuffer: function (conversationId) {
            var buf = this.streamBuffers[conversationId];
            if (!buf || !buf.length) return;
            // Find the last card and append buffered HTML
            var $view = (typeof $chatView === 'function') ? $chatView(conversationId) : $('#chatView');
            var $card = $view.find('.card.message-card').last();
            if ($card.length) {
                var $content = $card.find('.card-text .markdown-content, .card-text').first();
                if ($content.length) {
                    for (var i = 0; i < buf.length; i++) {
                        $content.append(buf[i]);
                    }
                }
            }
            delete this.streamBuffers[conversationId];
        },

        _syncStreamUI: function (conversationId) {
            if (this.streamControllers[conversationId]) {
                $('#sendMessageButton').hide();
                $('#stopResponseButton').show();
            } else {
                $('#sendMessageButton').show();
                $('#stopResponseButton').hide();
            }
        },

        // ---------------------------------------------------------------
        // Tab title sync
        // ---------------------------------------------------------------

        updateTitle: function (conversationId, title) {
            var tab = this.getTab(conversationId);
            if (tab && title) {
                tab.title = title;
                this.renderUI();
                this.persist();
            }
        },

        // ---------------------------------------------------------------
        // Rendering
        // ---------------------------------------------------------------

        renderUI: function () {
            this.renderTabBar();
            this.renderGearTabs();
        },

        renderTabBar: function () {
            var $bar = $('#conv-tab-bar');
            if (!$bar.length) return;
            // Hide when <=1 tab
            if (this.tabs.length <= 1) { $bar.removeClass('visible').empty(); return; }
            $bar.addClass('visible');
            var self = this;
            var html = '';
            for (var i = 0; i < this.tabs.length; i++) {
                var t = this.tabs[i];
                var active = (t.conversationId === this.focusedTabId) ? ' active' : '';
                var titleTrunc = (t.title || 'Untitled').substring(0, 20);
                if ((t.title || '').length > 20) titleTrunc += '\u2026';
                html += '<div class="conv-tab' + active + '" data-conv-id="' + t.conversationId + '" title="' + (t.title || '').replace(/"/g, '&quot;') + '">';
                html += '<span class="conv-tab-title">' + titleTrunc + '</span>';
                if (this.tabs.length > 1) {
                    html += '<button class="conv-tab-close" data-conv-id="' + t.conversationId + '">\u00d7</button>';
                }
                html += '</div>';
            }
            html += '<button class="conv-tab-new" id="conv-tab-new-btn" title="New tab">+</button>';
            $bar.html(html);

            // Handlers
            $bar.find('.conv-tab').off('click').on('click', function (e) {
                if ($(e.target).hasClass('conv-tab-close')) return;
                self.focusTab($(this).data('conv-id'));
            });
            $bar.find('.conv-tab-close').off('click').on('click', function (e) {
                e.stopPropagation();
                self.closeTab($(this).data('conv-id'));
            });
            $bar.find('#conv-tab-new-btn').off('click').on('click', function () {
                self._newTabFromButton();
            });
        },

        renderGearTabs: function () {
            // Render tab list in both inline and floating gear dropdowns
            var self = this;
            $('.gear-tab-nav').each(function () {
                var $nav = $(this);
                if (self.tabs.length <= 1) { $nav.hide(); $nav.next('.dropdown-divider.gear-tab-divider').hide(); return; }
                $nav.show(); $nav.next('.dropdown-divider.gear-tab-divider').show();
                var html = '';
                for (var i = 0; i < self.tabs.length; i++) {
                    var t = self.tabs[i];
                    var active = (t.conversationId === self.focusedTabId) ? ' active' : '';
                    var titleTrunc = (t.title || 'Untitled').substring(0, 25);
                    if ((t.title || '').length > 25) titleTrunc += '\u2026';
                    html += '<a class="dropdown-item gear-tab-item gear-domain-item' + active + '" href="#" data-conv-id="' + t.conversationId + '"><i class="fa fa-comment mr-2"></i>' + titleTrunc + '</a>';
                }
                $nav.html(html);
                $nav.find('.gear-tab-item').off('click').on('click', function (e) {
                    e.preventDefault();
                    self.focusTab($(this).data('conv-id'));
                });
            });
        },

        _newTabFromButton: function () {
            // Create new conversation and open in new tab
            if (typeof WorkspaceManager !== 'undefined' && WorkspaceManager.createTemporaryConversation) {
                WorkspaceManager.createTemporaryConversation();
            }
        },

        // ---------------------------------------------------------------
        // Persistence
        // ---------------------------------------------------------------

        persist: function () {
            try {
                var data = this.tabs.map(function (t) { return { conversationId: t.conversationId, title: t.title }; });
                localStorage.setItem(storageKey(), JSON.stringify({ tabs: data, focusedTabId: this.focusedTabId }));
            } catch (_e) {}
        },

        restore: function () {
            try {
                var raw = localStorage.getItem(storageKey());
                if (!raw) return false;
                var data = JSON.parse(raw);
                if (!data || !data.tabs || !data.tabs.length) return false;
                this.tabs = data.tabs;
                this.focusedTabId = data.focusedTabId || this.tabs[0].conversationId;
                return true;
            } catch (_e) { return false; }
        },

        clearTabs: function () {
            // Abort all streams
            var self = this;
            Object.keys(this.streamControllers).forEach(function (k) {
                try { self.streamControllers[k].cancel(); } catch (_e) {}
            });
            this.streamControllers = {};
            this.streamBuffers = {};
            // Remove panes on desktop and recreate a fresh #chatView
            if (!isMobileLayout()) {
                $('.chatView-pane').remove();
                var $container = $('#chatView-container');
                if ($container.length) {
                    $('<div id="chatView" class="chatView-pane row flex-grow-1 overflow-auto active"></div>').appendTo($container);
                }
            }
            this.tabs = [];
            this.focusedTabId = null;
            this.renderUI();
            this.persist();
        },

        // ---------------------------------------------------------------
        // Init
        // ---------------------------------------------------------------

        init: function (initialConversationId, initialTitle) {
            var self = this;
            var restored = this.restore();
            if (!restored && initialConversationId) {
                this.tabs = [{ conversationId: initialConversationId, title: initialTitle || 'Untitled' }];
                this.focusedTabId = initialConversationId;
            } else if (restored && initialConversationId) {
                // Ensure the loaded conversation is in the tab list
                if (!this.hasTab(initialConversationId)) {
                    // If only 1 persisted tab, replace it (user navigated away)
                    if (this.tabs.length === 1) {
                        this.tabs[0] = { conversationId: initialConversationId, title: initialTitle || 'Untitled' };
                    } else {
                        this.tabs.unshift({ conversationId: initialConversationId, title: initialTitle || 'Untitled' });
                    }
                }
                // The DOM currently shows initialConversationId, so set it as focused
                this.focusedTabId = initialConversationId;
            }
            // On desktop, rename the existing #chatView to the focused tab's pane
            if (!isMobileLayout() && this.focusedTabId) {
                this._ensureDesktopPanes();
            }
            this.renderUI();
            // Domain switch clears tabs
            this._lastDomain = (typeof currentDomain !== 'undefined' && currentDomain.domain) ? currentDomain.domain : null;
            $(document).off('domainChanged.tabManager').on('domainChanged.tabManager', function () {
                var newDomain = (typeof currentDomain !== 'undefined' && currentDomain.domain) ? currentDomain.domain : null;
                if (self._lastDomain && newDomain && self._lastDomain !== newDomain) {
                    self.clearTabs();
                }
                self._lastDomain = newDomain;
            });
        },

        _ensureDesktopPanes: function () {
            var $container = $('#chatView-container');
            if (!$container.length) return;
            // The initial chatView becomes the focused tab's pane
            var $existing = $('#chatView');
            if ($existing.length && this.focusedTabId) {
                $existing.attr('id', 'chatView-' + this.focusedTabId).addClass('chatView-pane active');
            }
        }
    };

    window.TabManager = TabManager;
})();
