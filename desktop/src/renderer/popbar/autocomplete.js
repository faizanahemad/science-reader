/**
 * autocomplete.js — PKB @reference autocomplete for PopBar input.
 * Detects @ trigger, fetches matching PKB items, renders dropdown, handles keyboard navigation.
 */
;(function () {
  'use strict'

  const api = window.electronAPI
  if (!api) return

  const DEBOUNCE_MS = 200
  const POPBAR_BAR_HEIGHT = 56
  const SECTION_CONFIG = [
    { key: 'memories', icon: '🧠', label: 'Memories', detail: item => truncate(item.statement, 60) },
    { key: 'contexts', icon: '📁', label: 'Contexts', detail: item => `${item.name || ''}${item.claim_count != null ? ' (' + item.claim_count + ')' : ''}` },
    { key: 'entities', icon: '👤', label: 'Entities', detail: item => `${item.name || ''} · ${item.entity_type || ''}` },
    { key: 'tags', icon: '🏷', label: 'Tags', detail: item => item.name || '' },
    { key: 'domains', icon: '🌐', label: 'Domains', detail: item => item.display_name || item.domain_name || '' }
  ]

  // ── State ──
  let container = null
  let items = [] // flat list of { el, friendlyId }
  let highlightIdx = -1
  let debounceTimer = null
  let abortCtrl = null
  let visible = false
  let lastPrefix = ''

  // ── DOM setup ──
  const input = document.querySelector('.popbar-input')
  const inputArea = document.querySelector('.popbar-input-area')
  if (!input || !inputArea) return

  container = document.createElement('div')
  container.className = 'pkb-autocomplete'
  inputArea.appendChild(container)

  // ── Helpers ──

  function truncate (str, max) {
    if (!str) return ''
    return str.length > max ? str.substring(0, max) + '…' : str
  }

  /**
   * Extract the @prefix from input value at current cursor position.
   * Returns the text after the last @ before cursor, or null if no active @.
   */
  function getAtPrefix () {
    const val = input.value
    const cursor = input.selectionStart
    // Look backward from cursor for @
    const before = val.substring(0, cursor)
    const atIdx = before.lastIndexOf('@')
    if (atIdx === -1) return null
    // Must be start of string or preceded by whitespace
    if (atIdx > 0 && !/\s/.test(before[atIdx - 1])) return null
    const prefix = before.substring(atIdx + 1)
    // No spaces allowed in prefix (friendly_ids don't have spaces)
    if (/\s/.test(prefix)) return null
    return prefix.length >= 1 ? prefix : null
  }

  /**
   * Replace the @prefix in input with @friendly_id + trailing space.
   */
  function insertReference (friendlyId) {
    const val = input.value
    const cursor = input.selectionStart
    const before = val.substring(0, cursor)
    const atIdx = before.lastIndexOf('@')
    if (atIdx === -1) return

    const replacement = '@' + friendlyId + ' '
    const newVal = val.substring(0, atIdx) + replacement + val.substring(cursor)
    input.value = newVal
    const newCursor = atIdx + replacement.length
    input.setSelectionRange(newCursor, newCursor)
  }

  // ── API call ──

  async function fetchAutocomplete (prefix) {
    if (abortCtrl) abortCtrl.abort()
    abortCtrl = new AbortController()

    try {
      const data = await api.invoke('popbar:pkb-autocomplete', { query: prefix })
      if (!data) return null
      return data
    } catch (err) {
      if (err.name !== 'AbortError') {
        console.warn('[Autocomplete] Fetch error:', err.message)
      }
      return null
    }
  }

  // ── Render ──

  function render (data) {
    // Clear previous
    while (container.firstChild) container.removeChild(container.firstChild)
    items = []
    highlightIdx = -1

    let totalItems = 0

    for (const cfg of SECTION_CONFIG) {
      const arr = data[cfg.key]
      if (!arr || arr.length === 0) continue

      // Section header
      const header = document.createElement('div')
      header.className = 'pkb-ac-section-header'
      header.textContent = cfg.icon + ' ' + cfg.label

      const section = document.createElement('div')
      section.className = 'pkb-ac-section'
      section.appendChild(header)

      for (const item of arr) {
        const el = document.createElement('div')
        el.className = 'pkb-ac-item'

        const iconSpan = document.createElement('span')
        iconSpan.className = 'pkb-ac-item-icon'
        iconSpan.textContent = cfg.icon

        const idSpan = document.createElement('span')
        idSpan.className = 'pkb-ac-item-id'
        idSpan.textContent = '@' + item.friendly_id

        const detailSpan = document.createElement('span')
        detailSpan.className = 'pkb-ac-item-detail'
        detailSpan.textContent = cfg.detail(item)

        el.appendChild(iconSpan)
        el.appendChild(idSpan)
        el.appendChild(detailSpan)

        const idx = items.length
        el.addEventListener('mousedown', (e) => {
          e.preventDefault() // prevent blur
          selectItem(idx)
        })
        el.addEventListener('mouseenter', () => {
          setHighlight(idx)
        })

        section.appendChild(el)
        items.push({ el, friendlyId: item.friendly_id })
        totalItems++
      }

      container.appendChild(section)
    }

    if (totalItems === 0) {
      hide()
      return
    }

    show()
    setHighlight(0)
  }

  // ── Show / hide ──

  function show () {
    if (visible) return
    visible = true
    container.classList.add('visible')
    resizeWindow()
  }

  function hide () {
    if (!visible) return
    visible = false
    container.classList.remove('visible')
    items = []
    highlightIdx = -1
    lastPrefix = ''
    if (abortCtrl) {
      abortCtrl.abort()
      abortCtrl = null
    }
    // Restore default popbar height
    api.send('popbar:resize', { width: 520, height: POPBAR_BAR_HEIGHT })
  }

  function isVisible () {
    return visible
  }

  function resizeWindow () {
    // Calculate needed height: popbar bar + autocomplete container
    const acHeight = Math.min(container.scrollHeight, 260)
    const totalHeight = POPBAR_BAR_HEIGHT + 4 + acHeight // 4px margin
    api.send('popbar:resize', { width: 520, height: Math.ceil(totalHeight) })
  }

  // ── Highlight / selection ──

  function setHighlight (idx) {
    if (highlightIdx >= 0 && highlightIdx < items.length) {
      items[highlightIdx].el.classList.remove('highlighted')
    }
    highlightIdx = idx
    if (highlightIdx >= 0 && highlightIdx < items.length) {
      items[highlightIdx].el.classList.add('highlighted')
      items[highlightIdx].el.scrollIntoView({ block: 'nearest' })
    }
  }

  function selectItem (idx) {
    if (idx < 0 || idx >= items.length) return
    insertReference(items[idx].friendlyId)
    hide()
    input.focus()
  }

  // ── Input event: detect @ prefix ──

  input.addEventListener('input', () => {
    const prefix = getAtPrefix()
    if (!prefix) {
      hide()
      return
    }

    if (prefix === lastPrefix) return
    lastPrefix = prefix

    clearTimeout(debounceTimer)
    debounceTimer = setTimeout(async () => {
      const data = await fetchAutocomplete(prefix)
      // Check prefix hasn't changed while waiting
      if (data && getAtPrefix() === prefix) {
        render(data)
      }
    }, DEBOUNCE_MS)
  })

  // ── Keyboard navigation ──

  document.addEventListener('keydown', (e) => {
    if (!visible) return

    if (e.key === 'ArrowDown') {
      e.preventDefault()
      e.stopPropagation()
      const next = (highlightIdx + 1) % items.length
      setHighlight(next)
      return
    }

    if (e.key === 'ArrowUp') {
      e.preventDefault()
      e.stopPropagation()
      const prev = (highlightIdx - 1 + items.length) % items.length
      setHighlight(prev)
      return
    }

    if (e.key === 'Enter' || e.key === 'Tab') {
      e.preventDefault()
      e.stopPropagation()
      if (highlightIdx >= 0) {
        selectItem(highlightIdx)
      }
      return
    }

    if (e.key === 'Escape') {
      e.preventDefault()
      e.stopPropagation()
      hide()
    }
  }, true) // capture phase to intercept before popbar.js

  // ── Hide on blur / outside click ──

  input.addEventListener('blur', () => {
    // Delay to allow mousedown on autocomplete items
    setTimeout(() => {
      if (!input.matches(':focus')) hide()
    }, 150)
  })

  document.addEventListener('click', (e) => {
    if (visible && !container.contains(e.target) && e.target !== input) {
      hide()
    }
  })

  // ── Expose ──
  window.PKBAutocomplete = { isVisible, hide }
  console.log('[Autocomplete] Module loaded')
})()
