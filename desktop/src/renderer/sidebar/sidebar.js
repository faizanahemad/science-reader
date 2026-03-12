/**
 * sidebar.js — Tab switching, settings panel (snap/dock/config/env), drag-drop.
 */
;(function () {
  'use strict'

  const tabs = document.querySelectorAll('#tab-bar .tab')
  const panels = document.querySelectorAll('#tab-content .tab-panel')

  // Settings panel elements
  const snapBtns = document.querySelectorAll('.snap-buttons-settings .snap-btn')
  const dockBtn = document.getElementById('dock-mode-btn')
  const configEditor = document.getElementById('opencode-config-editor')
  const configSaveBtn = document.getElementById('config-save-btn')
  const configResetBtn = document.getElementById('config-reset-btn')
  const configStatus = document.getElementById('config-status')
  const envVarsList = document.getElementById('env-vars-list')
  const envAddBtn = document.getElementById('env-add-btn')
  const notifMuteBtn = document.getElementById('notif-mute-btn')

  // ── Tab switching ──
  tabs.forEach(tab => {
    tab.addEventListener('click', () => {
      const target = tab.dataset.tab
      if (!target) return

      tabs.forEach(t => t.classList.remove('active'))
      tab.classList.add('active')

      panels.forEach(p => {
        p.classList.toggle('active', p.dataset.panel === target)
      })

      if (window.electronAPI) {
        window.electronAPI.send('sidebar:tab-changed', target)
      }

      // Load settings data when settings tab is opened
      if (target === 'settings' && window.electronAPI) {
        _loadSettings()
      }
    })
  })

  // ── Manual window drag (drag handle) ──
  // type:'panel' windows on macOS ignore -webkit-app-region: drag
  const dragHandle = document.getElementById('drag-handle')
  let _dragging = false
  let _dragStartX = 0
  let _dragStartY = 0

  dragHandle.addEventListener('mousedown', (e) => {
    _dragging = true
    _dragStartX = e.screenX
    _dragStartY = e.screenY
  })

  document.addEventListener('mousemove', (e) => {
    if (!_dragging) return
    const dx = e.screenX - _dragStartX
    const dy = e.screenY - _dragStartY
    _dragStartX = e.screenX
    _dragStartY = e.screenY
    if (window.electronAPI) {
      window.electronAPI.send('sidebar:window-drag', { dx, dy })
    }
  })

  document.addEventListener('mouseup', () => {
    _dragging = false
  })

  // ── Snap buttons (inside settings) ──
  snapBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      const mode = btn.dataset.snap
      if (!mode) return

      snapBtns.forEach(b => b.classList.remove('active'))
      btn.classList.add('active')

      if (window.electronAPI) {
        window.electronAPI.send('sidebar:snap', mode)
      }
    })
  })

  if (window.electronAPI) {
    window.electronAPI.on('sidebar:snap-changed', (mode) => {
      snapBtns.forEach(b => {
        b.classList.toggle('active', b.dataset.snap === mode)
      })
    })
  }

  // ── Dock mode toggle (overlay ↔ push) ──
  if (dockBtn && window.electronAPI) {
    dockBtn.addEventListener('click', () => {
      const current = dockBtn.dataset.dock
      const next = current === 'overlay' ? 'push' : 'overlay'
      dockBtn.dataset.dock = next
      _updateDockBtn(next)
      window.electronAPI.send('sidebar:dock-mode', next)
    })

    window.electronAPI.on('sidebar:dock-mode-changed', (mode) => {
      dockBtn.dataset.dock = mode
      _updateDockBtn(mode)
    })
  }

  function _updateDockBtn (mode) {
    if (!dockBtn) return
    if (mode === 'push') {
      dockBtn.textContent = 'P'
      dockBtn.title = 'Push mode (click for overlay)'
      dockBtn.classList.add('push-active')
    } else {
      dockBtn.textContent = 'O'
      dockBtn.title = 'Overlay mode (click to push)'
      dockBtn.classList.remove('push-active')
    }
  }

  // ── App mode toggle (sidebar ↔ app) ──
  const appModeBtn = document.getElementById('app-mode-btn')

  if (appModeBtn && window.electronAPI) {
    appModeBtn.addEventListener('click', () => {
      const current = appModeBtn.dataset.appmode
      const next = current === 'sidebar' ? 'app' : 'sidebar'
      appModeBtn.dataset.appmode = next
      _updateAppModeBtn(next)
      window.electronAPI.send('sidebar:app-mode', next)
    })

    window.electronAPI.on('sidebar:app-mode-changed', (mode) => {
      appModeBtn.dataset.appmode = mode
      _updateAppModeBtn(mode)
    })
  }

  function _updateAppModeBtn (mode) {
    if (!appModeBtn) return
    if (mode === 'app') {
      appModeBtn.textContent = 'A'
      appModeBtn.title = 'App mode (click for sidebar)'
      appModeBtn.classList.add('push-active')
    } else {
      appModeBtn.textContent = 'S'
      appModeBtn.title = 'Sidebar mode (click for app mode)'
      appModeBtn.classList.remove('push-active')
    }
  }

  // ── Notification mute toggle ──
  if (notifMuteBtn && window.electronAPI) {
    // Load initial state
    window.electronAPI.invoke('settings:get-notifications-muted').then((muted) => {
      _updateNotifMuteBtn(!!muted)
    })

    notifMuteBtn.addEventListener('click', () => {
      const current = notifMuteBtn.dataset.muted === 'true'
      const next = !current
      _updateNotifMuteBtn(next)
      window.electronAPI.invoke('settings:set-notifications-muted', next)
    })
  }

  function _updateNotifMuteBtn (muted) {
    if (!notifMuteBtn) return
    notifMuteBtn.dataset.muted = muted ? 'true' : 'false'
    notifMuteBtn.textContent = muted ? '🔕' : '🔔'
    notifMuteBtn.title = muted ? 'Notifications muted (click to unmute)' : 'Notifications on (click to mute)'
    if (muted) {
      notifMuteBtn.classList.add('push-active')
    } else {
      notifMuteBtn.classList.remove('push-active')
    }
  }

  // ── Notification click routing (tab flash from native notification click) ──
  if (window.electronAPI) {
    window.electronAPI.on('notification:clicked', (data) => {
      if (!data || !data.action) return
      if (data.action.type === 'flash-tab' && data.action.tab) {
        // Switch to the target tab
        const targetTab = document.querySelector(`[data-tab="${data.action.tab}"]`)
        if (targetTab) targetTab.click()
        // Flash it
        targetTab?.classList.add('flash-notify')
        setTimeout(() => targetTab?.classList.remove('flash-notify'), 3000)
      }
    })
  }

  // ── OpenCode config editor ──
  let _defaultConfig = ''

  async function _loadSettings () {
    if (!window.electronAPI) return
    try {
      const data = await window.electronAPI.invoke('settings:get-opencode-config')
      if (data) {
        _defaultConfig = data.defaultConfig || ''
        configEditor.value = data.customConfig || _defaultConfig
      }
      // Load env vars
      const envData = await window.electronAPI.invoke('settings:get-env-vars')
      _renderEnvVars(envData || {})
    } catch (err) {
      console.warn('[Settings] Failed to load:', err.message)
    }
  }

  if (configSaveBtn) {
    configSaveBtn.addEventListener('click', async () => {
      if (!window.electronAPI) return
      try {
        // Validate JSON
        const text = configEditor.value.trim()
        if (text) JSON.parse(text) // throws on invalid JSON
        await window.electronAPI.invoke('settings:set-opencode-config', text)
        _showStatus('Saved', 'success')
      } catch (err) {
        _showStatus(err.message.includes('JSON') ? 'Invalid JSON' : err.message, 'error')
      }
    })
  }

  if (configResetBtn) {
    configResetBtn.addEventListener('click', async () => {
      configEditor.value = _defaultConfig
      if (window.electronAPI) {
        await window.electronAPI.invoke('settings:set-opencode-config', '')
        _showStatus('Reset to default', 'success')
      }
    })
  }

  function _showStatus (text, type) {
    if (!configStatus) return
    configStatus.textContent = text
    configStatus.className = 'config-status ' + type
    setTimeout(() => { configStatus.textContent = '' }, 2500)
  }

  // ── Environment variables ──
  function _renderEnvVars (vars) {
    if (!envVarsList) return
    envVarsList.innerHTML = ''
    const entries = Object.entries(vars)
    if (entries.length === 0) {
      _addEnvRow('', '')
      return
    }
    entries.forEach(([key, val]) => _addEnvRow(key, val))
  }

  function _addEnvRow (key, val) {
    const row = document.createElement('div')
    row.className = 'env-var-row'
    row.innerHTML = `
      <input type="text" class="env-key" placeholder="KEY" value="${_escHtml(key)}">
      <input type="text" class="env-val" placeholder="value" value="${_escHtml(val)}">
      <button class="env-remove-btn" title="Remove">✕</button>
    `
    row.querySelector('.env-remove-btn').addEventListener('click', () => {
      row.remove()
      _saveEnvVars()
    })
    // Auto-save on blur
    row.querySelectorAll('input').forEach(inp => {
      inp.addEventListener('blur', () => _saveEnvVars())
      inp.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
          e.preventDefault()
          _saveEnvVars()
        }
      })
    })
    envVarsList.appendChild(row)
  }

  if (envAddBtn) {
    envAddBtn.addEventListener('click', () => {
      _addEnvRow('', '')
      // Focus the new key input
      const rows = envVarsList.querySelectorAll('.env-var-row')
      const lastRow = rows[rows.length - 1]
      if (lastRow) lastRow.querySelector('.env-key').focus()
    })
  }

  function _saveEnvVars () {
    if (!window.electronAPI) return
    const vars = {}
    envVarsList.querySelectorAll('.env-var-row').forEach(row => {
      const key = row.querySelector('.env-key').value.trim()
      const val = row.querySelector('.env-val').value
      if (key) vars[key] = val
    })
    window.electronAPI.invoke('settings:set-env-vars', vars)
  }

  function _escHtml (str) {
    return String(str).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  }

  // ── M2.1: Focus state handling ──
  if (window.electronAPI) {
    window.electronAPI.on('focus:state-changed', ({ state }) => {
      document.body.classList.remove('focus-hover', 'focus-active')
      if (state === 'hover') {
        document.body.classList.add('focus-hover')
      } else if (state === 'active') {
        document.body.classList.add('focus-active')
      }
    })
  }

  // ── M2.1: Escape key → focus state machine ──
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      e.preventDefault()
      window.electronAPI.send('focus:escape')
    }
  })

// ── M4.1: Drag-and-drop file handling ──
;(function setupDropZone () {
  const overlay = document.getElementById('drop-zone-overlay')
  if (!overlay || !window.electronAPI) return

  let dragCounter = 0

  document.addEventListener('dragenter', (e) => {
    e.preventDefault()
    e.stopPropagation()
    dragCounter++
    if (e.dataTransfer && e.dataTransfer.types.includes('Files')) {
      overlay.classList.add('active')
    }
  })

  document.addEventListener('dragleave', (e) => {
    e.preventDefault()
    e.stopPropagation()
    dragCounter--
    if (dragCounter <= 0) {
      dragCounter = 0
      overlay.classList.remove('active')
    }
  })

  document.addEventListener('dragover', (e) => {
    e.preventDefault()
    e.stopPropagation()
  })

  document.addEventListener('drop', (e) => {
    e.preventDefault()
    e.stopPropagation()
    dragCounter = 0
    overlay.classList.remove('active')

    const files = e.dataTransfer ? e.dataTransfer.files : null
    if (!files || files.length === 0) return

    const file = files[0] // Single file only
    if (typeof window.electronAPI.getPathForFile === 'function') {
      const filePath = window.electronAPI.getPathForFile(file)
      if (filePath) {
        window.electronAPI.send('file-drop:open-global-docs', { filePath })
        return
      }
    }
    console.warn('[Sidebar] Could not get native file path for dropped file')
  })
})()

})()
