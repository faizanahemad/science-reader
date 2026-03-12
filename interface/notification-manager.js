/**
 * notification-manager.js — Generic notification system for all interfaces.
 *
 * Auto-detects environment (Electron desktop vs browser) and dispatches
 * notifications through the appropriate transport:
 *   - Electron: IPC → main process → native macOS Notification API
 *   - Browser:  Web Notification API (requires user permission grant)
 *
 * Usage:
 *   NotificationManager.notify({
 *     title: 'Clarification Needed',
 *     body:  'The assistant has questions for you.',
 *     type:  'clarification',
 *     action: { type: 'open-modal', modal: 'tool-call' }
 *   });
 *
 * Notification types (extensible — just use any string):
 *   'clarification' — LLM asks clarification questions
 *   'tool_request'  — Any interactive tool needs user input
 *   'info'          — General informational
 *   'warning'       — Warning alert
 *   'error'         — Error alert
 *   'success'       — Success confirmation
 *
 * Action schema (what happens on click):
 *   { type: 'open-modal', modal: 'tool-call' | 'clarifications' | ... }
 *   { type: 'flash-tab',  tab: 'chat' | 'opencode' | 'terminal' | 'settings' }
 *   { type: 'navigate',   url: '...' }
 *   { type: 'none' }  // no click action
 *
 * The module is environment-agnostic — it works in Electron sidebar,
 * Electron chat WebContentsView, regular Chrome tab, and mobile browser.
 */
;(function () {
  'use strict'

  // ── State ──────────────────────────────────────────────────────────

  var _muted = false
  var _browserPermission = typeof Notification !== 'undefined' ? Notification.permission : 'denied'
  var _pendingQueue = [] // queued while permission is being requested
  var _permissionRequesting = false

  // ── Environment detection ──────────────────────────────────────────

  function _isElectron () {
    return !!(window.__isElectronDesktop && window.electronAPI)
  }

  function _isBrowserNotificationSupported () {
    return typeof Notification !== 'undefined' && 'Notification' in window
  }

  // ── Core API ───────────────────────────────────────────────────────

  /**
   * Show a notification.
   *
   * @param {Object} opts
   * @param {string} opts.title    - Notification title
   * @param {string} opts.body     - Notification body text
   * @param {string} [opts.type]   - Notification type (clarification, tool_request, info, etc.)
   * @param {Object} [opts.action] - Click action descriptor { type, ... }
   * @param {string} [opts.tag]    - Dedupe tag (replaces existing notification with same tag)
   * @param {boolean} [opts.silent] - If true, suppress notification sound
   */
  function notify (opts) {
    if (!opts || !opts.title) return
    if (_muted) return

    var payload = {
      title: opts.title || '',
      body: opts.body || '',
      type: opts.type || 'info',
      action: opts.action || { type: 'none' },
      tag: opts.tag || '',
      silent: !!opts.silent
    }

    if (_isElectron()) {
      _notifyElectron(payload)
    } else if (_isBrowserNotificationSupported()) {
      _notifyBrowser(payload)
    }
    // else: environment doesn't support notifications, silently skip
  }

  // ── Electron transport ─────────────────────────────────────────────

  function _notifyElectron (payload) {
    // Send to main process via IPC — main process creates native notification
    window.electronAPI.send('notification:show', payload)
  }

  // ── Browser transport ──────────────────────────────────────────────

  function _notifyBrowser (payload) {
    if (_browserPermission === 'granted') {
      _createBrowserNotification(payload)
    } else if (_browserPermission === 'default') {
      // Permission not yet asked — queue and request
      _pendingQueue.push(payload)
      _requestBrowserPermission()
    }
    // 'denied' — user blocked notifications, silently skip
  }

  function _createBrowserNotification (payload) {
    try {
      var n = new Notification(payload.title, {
        body: payload.body,
        tag: payload.tag || undefined,
        silent: payload.silent,
        icon: '/interface/icon-192.png' // app icon if available
      })

      n.onclick = function () {
        // Focus the tab/window
        window.focus()
        n.close()
        // Route the action
        _handleClickAction(payload.action)
      }
    } catch (e) {
      console.warn('[NotificationManager] Browser notification failed:', e)
    }
  }

  function _requestBrowserPermission () {
    if (_permissionRequesting) return
    _permissionRequesting = true

    Notification.requestPermission().then(function (permission) {
      _browserPermission = permission
      _permissionRequesting = false

      if (permission === 'granted') {
        // Flush queued notifications
        var queue = _pendingQueue.splice(0)
        for (var i = 0; i < queue.length; i++) {
          _createBrowserNotification(queue[i])
        }
      } else {
        _pendingQueue = []
      }
    }).catch(function () {
      _permissionRequesting = false
      _pendingQueue = []
    })
  }

  // ── Click action routing ───────────────────────────────────────────

  /**
   * Handle a notification click action. Works in both Electron and browser.
   * In Electron, this is called from the desktop-bridge when main process
   * sends 'notification:clicked'. In browser, called directly from onclick.
   */
  function _handleClickAction (action) {
    if (!action || action.type === 'none') return

    switch (action.type) {
      case 'open-modal':
        _openModal(action.modal)
        break

      case 'flash-tab':
        _flashTab(action.tab)
        break

      case 'navigate':
        if (action.url) window.location.href = action.url
        break

      default:
        console.log('[NotificationManager] Unknown action type:', action.type)
    }
  }

  function _openModal (modalName) {
    if (!modalName) return
    // Map modal names to jQuery selectors
    var modalMap = {
      'tool-call': '#tool-call-modal',
      'clarifications': '#clarifications-modal',
      'pkb': '#pkb-search-modal'
    }
    var selector = modalMap[modalName]
    if (selector && typeof $ !== 'undefined') {
      $(selector).modal('show')
    }
  }

  function _flashTab (tabName) {
    if (!tabName) return

    // Electron sidebar: send IPC to switch + flash tab
    if (_isElectron()) {
      window.electronAPI.send('sidebar:tab-changed', tabName)
    }

    // Also flash the tab button in sidebar UI if present
    var $tab = $('[data-tab="' + tabName + '"]')
    if ($tab.length) {
      $tab.addClass('flash-notify')
      setTimeout(function () { $tab.removeClass('flash-notify') }, 3000)
    }
  }

  // ── Mute control ───────────────────────────────────────────────────

  function setMuted (muted) {
    _muted = !!muted
  }

  function isMuted () {
    return _muted
  }

  // ── Permission helper (browser) ────────────────────────────────────

  /**
   * Explicitly request browser notification permission.
   * Must be called from a user gesture (click handler).
   * Returns a Promise that resolves to the permission state.
   */
  function requestPermission () {
    if (_isElectron()) {
      // Electron doesn't need permission for main-process notifications
      return Promise.resolve('granted')
    }
    if (!_isBrowserNotificationSupported()) {
      return Promise.resolve('denied')
    }
    return Notification.requestPermission().then(function (perm) {
      _browserPermission = perm
      return perm
    })
  }

  /**
   * Get current permission state.
   * @returns {'granted'|'denied'|'default'|'electron'}
   */
  function getPermissionState () {
    if (_isElectron()) return 'electron'
    if (!_isBrowserNotificationSupported()) return 'denied'
    return _browserPermission
  }

  // ── Listen for Electron click-back events ──────────────────────────

  if (typeof window !== 'undefined' && window.__isElectronDesktop && window.electronAPI) {
    window.electronAPI.on('notification:clicked', function (data) {
      if (data && data.action) {
        _handleClickAction(data.action)
      }
    })
  }

  // ── Public API ─────────────────────────────────────────────────────

  window.NotificationManager = {
    notify: notify,
    setMuted: setMuted,
    isMuted: isMuted,
    requestPermission: requestPermission,
    getPermissionState: getPermissionState,
    // Expose for desktop-bridge to call directly
    handleClickAction: _handleClickAction
  }
})()
