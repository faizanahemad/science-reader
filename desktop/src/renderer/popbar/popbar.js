/**
 * popbar.js — PopBar renderer logic.
 * Handles action selection, keyboard shortcuts, input history, and focus management.
 */
;(function () {
  'use strict'

  const api = window.electronAPI
  if (!api) {
    console.warn('[PopBar] electronAPI not available')
    return
  }

  // ── DOM references ──
  const popbar = document.querySelector('.popbar')
  const actionBtns = document.querySelectorAll('.popbar-actions .popbar-btn:not(.popbar-btn-slot)')
  const input = document.querySelector('.popbar-input')
  const contextChips = document.querySelector('.popbar-context-chips')

  // ── State ──
  let currentAction = 'ask'
  const inputHistory = []
  const MAX_HISTORY = 20
  let historyIndex = -1
  let historyDraft = '' // saves current input when navigating history

  // ── Action selection ──

  function selectAction (action) {
    currentAction = action
    actionBtns.forEach(btn => {
      btn.classList.toggle('active', btn.dataset.action === action)
    })
    updatePlaceholder()
  }

  function updatePlaceholder () {
    const placeholders = {
      ask: 'Ask anything...',
      'memory-save': 'What to remember...',
      explain: 'Paste text to explain...',
      summarize: 'Paste text to summarize...',
      screenshot: 'Describe what to capture...',
      'memory-search': 'Search your memory...',
      context: 'Add context...',
      'generate-image': 'Describe the image...'
    }
    input.placeholder = placeholders[currentAction] || 'Ask anything...'
  }

  // Click handlers for action buttons
  actionBtns.forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.preventDefault()
      selectAction(btn.dataset.action)
      input.focus()
      // Activate on interaction
      api.send('popbar:activate')
    })
  })

  // ── Input history navigation ──

  function pushHistory (text) {
    if (!text.trim()) return
    // Avoid duplicates at the end
    if (inputHistory.length > 0 && inputHistory[inputHistory.length - 1] === text) return
    inputHistory.push(text)
    if (inputHistory.length > MAX_HISTORY) inputHistory.shift()
    historyIndex = -1
    historyDraft = ''
  }

  function navigateHistory (direction) {
    if (inputHistory.length === 0) return

    if (direction === 'up') {
      if (historyIndex === -1) {
        // Save current input as draft before navigating
        historyDraft = input.value
        historyIndex = inputHistory.length - 1
      } else if (historyIndex > 0) {
        historyIndex--
      }
      input.value = inputHistory[historyIndex]
    } else if (direction === 'down') {
      if (historyIndex === -1) return
      if (historyIndex < inputHistory.length - 1) {
        historyIndex++
        input.value = inputHistory[historyIndex]
      } else {
        // Back to draft
        historyIndex = -1
        input.value = historyDraft
      }
    }

    // Move cursor to end
    input.setSelectionRange(input.value.length, input.value.length)
  }

  // ── Context helpers ──

  function getContext () {
    // Collect context chips if any are visible
    const chips = contextChips.querySelectorAll('.popbar-chip')
    if (chips.length === 0) return null
    return Array.from(chips).map(c => c.dataset.context).filter(Boolean)
  }

  // ── Execute action ──

  function executeAction (opts = {}) {
    const text = input.value.trim()
    if (!text && currentAction !== 'screenshot') return

    const payload = {
      action: currentAction,
      text,
      context: getContext()
    }
    if (opts.escalate) payload.escalate = true

    api.send('popbar:action', payload)
    pushHistory(text)

    // M3.3: Show dropdown with streaming state
    if (window.PopBarDropdown) {
      window.PopBarDropdown.showStreaming(currentAction, text, false)
    }

    input.value = ''
    historyIndex = -1
    historyDraft = ''
  }

  // ── Keyboard shortcuts ──

  document.addEventListener('keydown', (e) => {
    // M7.4: Defer to autocomplete when visible
    if (window.PKBAutocomplete && window.PKBAutocomplete.isVisible()) {
      if (['ArrowUp', 'ArrowDown', 'Enter', 'Tab', 'Escape'].includes(e.key)) {
        return // autocomplete.js handles these via its own capture-phase listener
      }
    }

    const isMeta = e.metaKey || e.ctrlKey

    // Enter → execute action
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      if (isMeta) {
        executeAction({ escalate: true })
      } else {
        executeAction()
      }
      return
    }

    // Escape → close dropdown first, then focus state machine
    if (e.key === 'Escape') {
      e.preventDefault()
      if (window.PopBarDropdown && window.PopBarDropdown.isVisible()) {
        window.PopBarDropdown.hide()
      } else {
        api.send('popbar:escape')
      }
      return
    }

    // Tab → cycle action buttons
    if (e.key === 'Tab') {
      e.preventDefault()
      const actions = Array.from(actionBtns)
      const currentIdx = actions.findIndex(b => b.dataset.action === currentAction)
      const nextIdx = e.shiftKey
        ? (currentIdx - 1 + actions.length) % actions.length
        : (currentIdx + 1) % actions.length
      selectAction(actions[nextIdx].dataset.action)
      return
    }

    // Number keys 1-8 when input is empty → select action by index
    if (input.value === '' && !isMeta && !e.altKey && !e.shiftKey) {
      const num = parseInt(e.key, 10)
      if (num >= 1 && num <= 8 && num <= actionBtns.length) {
        e.preventDefault()
        selectAction(actionBtns[num - 1].dataset.action)
        return
      }
    }

    // Up/Down → navigate input history
    if (e.key === 'ArrowUp') {
      e.preventDefault()
      navigateHistory('up')
      return
    }
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      navigateHistory('down')
      return
    }
  })

  // ── Focus management ──

  // Activate on input interaction
  input.addEventListener('focus', () => {
    api.send('popbar:activate')
  })

  input.addEventListener('click', () => {
    api.send('popbar:activate')
  })

  // Listen for focus state changes from main process
  api.on('focus:state-changed', ({ state }) => {
    popbar.classList.remove('focus-hover', 'focus-active')
    if (state === 'hover') {
      popbar.classList.add('focus-hover')
    } else if (state === 'active') {
      popbar.classList.add('focus-active')
      // Restore input focus when entering active state
      input.focus()
    }
  })

  // ── Context update listener ──
  api.on('popbar:context-update', (data) => {
    // M6.3: Render context chips from ContextManager output
    if (data && data.chips && data.chips.length > 0) {
      contextChips.classList.add('visible')
      const SAVEABLE_TYPES = ['selection', 'url', 'manual', 'screenshot']
      contextChips.innerHTML = data.chips.map(chip => {
        const escaped = (chip.value || '').replace(/"/g, '&quot;')
        const isSaveable = SAVEABLE_TYPES.includes(chip.type)
        const saveBtn = isSaveable ? '<span class="popbar-chip-save" title="Save to memory">⊕</span>' : ''
        return `<span class="popbar-chip" data-context="${escaped}" data-type="${chip.type || ''}">` +
          `${chip.label}${saveBtn}<span class="popbar-chip-remove">×</span></span>`
      }).join('')
      // Chip removal click handler
      contextChips.querySelectorAll('.popbar-chip-remove').forEach(btn => {
        btn.addEventListener('click', (e) => {
          e.stopPropagation()
          const chip = btn.parentElement
          chip.remove()
          if (contextChips.querySelectorAll('.popbar-chip').length === 0) {
            contextChips.classList.remove('visible')
          }
        })
      })
      // M7.5: Chip save-to-memory click handler
      contextChips.querySelectorAll('.popbar-chip-save').forEach(btn => {
        btn.addEventListener('click', (e) => {
          e.stopPropagation()
          const chip = btn.parentElement
          const text = chip.dataset.context || ''
          if (!text.trim() || btn.dataset.saving) return
          btn.dataset.saving = '1'
          btn.textContent = '⏳'
          btn.style.pointerEvents = 'none'
          api.send('popbar:memory-quick-save', { text })
          // Optimistic: show success after brief delay (save result also updates dropdown if open)
          setTimeout(() => { btn.textContent = '✓' }, 1500)
        })
      })
      // Chip click → prefill input with chip value
      contextChips.querySelectorAll('.popbar-chip').forEach(chip => {
        chip.addEventListener('click', (e) => {
          if (e.target.classList.contains('popbar-chip-remove') || e.target.classList.contains('popbar-chip-save')) return
          input.value = chip.dataset.context || ''
          input.focus()
        })
      })
    } else {
      contextChips.classList.remove('visible')
      contextChips.innerHTML = ''
    }
  })

  // ── Initialize ──
  selectAction('ask')
  // Focus input after a brief delay (replaces autofocus attribute)
  setTimeout(() => input.focus(), 50)

// ── M4.1: Drag-and-drop file handling ──
;(function setupPopBarDrop () {
  if (!window.electronAPI) return

  let dragCounter = 0
  const popbarEl = document.querySelector('.popbar')

  document.addEventListener('dragenter', (e) => {
    e.preventDefault()
    e.stopPropagation()
    dragCounter++
    if (e.dataTransfer && e.dataTransfer.types.includes('Files')) {
      if (popbarEl) popbarEl.classList.add('drop-active')
    }
  })

  document.addEventListener('dragleave', (e) => {
    e.preventDefault()
    e.stopPropagation()
    dragCounter--
    if (dragCounter <= 0) {
      dragCounter = 0
      if (popbarEl) popbarEl.classList.remove('drop-active')
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
    if (popbarEl) popbarEl.classList.remove('drop-active')

    const files = e.dataTransfer ? e.dataTransfer.files : null
    if (!files || files.length === 0) return

    const file = files[0]
    if (typeof window.electronAPI.getPathForFile === 'function') {
      const filePath = window.electronAPI.getPathForFile(file)
      if (filePath) {
        api.send('popbar:file-drop', { filePath })
        return
      }
    }
    console.warn('[PopBar] Could not get native file path for dropped file')
  })
})()

})()
