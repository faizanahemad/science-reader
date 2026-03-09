/**
 * dropdown.js — PopBar results dropdown module (M3.3).
 * Streaming markdown rendering, code highlighting, action buttons (Copy, Replace, Expand).
 * Loaded after popbar.js; exposes window.PopBarDropdown.
 */
;(function () {
  'use strict'

  // Markdown rendering is provided by preload via electronAPI.renderMarkdown()

  const api = window.electronAPI
  if (!api) {
    console.warn('[Dropdown] electronAPI not available')
    return
  }

  // ── DOM references ──
  const dropdown = document.getElementById('popbar-dropdown')
  const POPBAR_BAR_HEIGHT = 56
  const MAX_DROPDOWN_HEIGHT = 380

  // ── State ──
  let visible = false
  let streaming = false
  let accumulatedText = ''
  let currentQuery = ''
  let hasSelection = false
  let renderTimer = null
  const RENDER_DEBOUNCE = 50

  // ── Internal DOM structure ──
  // Built dynamically: toolStatusBar | contentArea | errorBanner | actionsBar
  let toolStatusBar = null
  let contentArea = null
  let errorBanner = null
  let actionsBar = null
  let expandMenu = null
  let loadingIndicator = null

  function buildDropdownDOM () {
    dropdown.innerHTML = ''

    toolStatusBar = document.createElement('div')
    toolStatusBar.className = 'dropdown-tool-status'
    toolStatusBar.style.display = 'none'
    dropdown.appendChild(toolStatusBar)

    contentArea = document.createElement('div')
    contentArea.className = 'dropdown-content'
    dropdown.appendChild(contentArea)

    errorBanner = document.createElement('div')
    errorBanner.className = 'dropdown-error'
    errorBanner.style.display = 'none'
    dropdown.appendChild(errorBanner)

    actionsBar = document.createElement('div')
    actionsBar.className = 'dropdown-actions'
    actionsBar.style.display = 'none'
    dropdown.appendChild(actionsBar)
  }

  function buildLoadingIndicator () {
    const el = document.createElement('div')
    el.className = 'dropdown-loading'
    el.innerHTML =
      '<div class="dropdown-loading-dot"></div>' +
      '<div class="dropdown-loading-dot"></div>' +
      '<div class="dropdown-loading-dot"></div>' +
      '<span>Thinking…</span>'
    return el
  }

  function buildActionButtons () {
    actionsBar.innerHTML = ''
    actionsBar.style.display = 'flex'

    // Copy button — always shown
    const copyBtn = document.createElement('button')
    copyBtn.className = 'dropdown-btn dropdown-btn-primary'
    copyBtn.textContent = 'Copy'
    copyBtn.addEventListener('click', () => {
      api.send('popbar:copy', { text: accumulatedText })
      copyBtn.textContent = 'Copied ✓'
      setTimeout(() => { copyBtn.textContent = 'Copy' }, 1500)
    })
    actionsBar.appendChild(copyBtn)

    // Replace button — only when selection exists
    if (hasSelection) {
      const replaceBtn = document.createElement('button')
      replaceBtn.className = 'dropdown-btn'
      replaceBtn.textContent = 'Replace'
      replaceBtn.addEventListener('click', () => {
        api.send('popbar:replace', { text: accumulatedText })
        replaceBtn.textContent = 'Replaced ✓'
        setTimeout(() => { replaceBtn.textContent = 'Replace' }, 1500)
      })
      actionsBar.appendChild(replaceBtn)
    }

    // Expand button — always shown, with sub-menu
    const expandWrapper = document.createElement('div')
    expandWrapper.style.position = 'relative'

    const expandBtn = document.createElement('button')
    expandBtn.className = 'dropdown-btn'
    expandBtn.textContent = 'Expand ▾'
    expandBtn.addEventListener('click', (e) => {
      e.stopPropagation()
      expandMenu.classList.toggle('visible')
    })
    expandWrapper.appendChild(expandBtn)

    expandMenu = document.createElement('div')
    expandMenu.className = 'expand-menu'

    const newConvItem = document.createElement('div')
    newConvItem.className = 'expand-menu-item'
    newConvItem.textContent = 'New Conversation'
    newConvItem.addEventListener('click', () => {
      api.send('popbar:expand', { mode: 'new', query: currentQuery, response: accumulatedText })
      expandMenu.classList.remove('visible')
    })
    expandMenu.appendChild(newConvItem)

    const activeConvItem = document.createElement('div')
    activeConvItem.className = 'expand-menu-item'
    activeConvItem.textContent = 'Add to Active Conversation'
    activeConvItem.addEventListener('click', () => {
      api.send('popbar:expand', { mode: 'active', query: currentQuery, response: accumulatedText })
      expandMenu.classList.remove('visible')
    })
    expandMenu.appendChild(activeConvItem)

    expandWrapper.appendChild(expandMenu)
    actionsBar.appendChild(expandWrapper)

    // Close expand menu when clicking elsewhere
    document.addEventListener('click', closeExpandMenu)
  }

  function closeExpandMenu () {
    if (expandMenu) expandMenu.classList.remove('visible')
  }

  // ── Resize helper ──
  function updateWindowSize () {
    if (!visible) {
      api.send('popbar:resize', { width: 520, height: POPBAR_BAR_HEIGHT })
      return
    }
    // Measure actual dropdown content height
    const dropdownRect = dropdown.getBoundingClientRect()
    const contentHeight = Math.min(dropdownRect.height, MAX_DROPDOWN_HEIGHT)
    const totalHeight = POPBAR_BAR_HEIGHT + 4 + contentHeight // 4px for margin-top
    api.send('popbar:resize', { width: 520, height: Math.ceil(totalHeight) })
  }

  // ── Render markdown ──
  function renderMarkdown () {
    if (!contentArea) return
    try {
      contentArea.innerHTML = api.renderMarkdown(accumulatedText)
    } catch (err) {
      console.error('[Dropdown] Markdown parse error:', err)
      contentArea.textContent = accumulatedText
    }
    updateWindowSize()
  }

  function debouncedRender () {
    if (renderTimer) clearTimeout(renderTimer)
    renderTimer = setTimeout(renderMarkdown, RENDER_DEBOUNCE)
  }

  // ── Public API ──

  function showStreaming (_action, query, selectionFlag) {
    buildDropdownDOM()
    accumulatedText = ''
    currentQuery = query || ''
    hasSelection = !!selectionFlag
    streaming = true

    // Show loading indicator
    loadingIndicator = buildLoadingIndicator()
    contentArea.appendChild(loadingIndicator)

    // Show the dropdown
    dropdown.classList.add('visible')
    visible = true
    updateWindowSize()
  }

  function appendChunk (text) {
    if (!streaming) return
    // Remove loading indicator on first chunk
    if (loadingIndicator && loadingIndicator.parentNode) {
      loadingIndicator.parentNode.removeChild(loadingIndicator)
      loadingIndicator = null
    }
    accumulatedText += text
    debouncedRender()
  }

  function finishStreaming () {
    streaming = false
    // Final render (clear any pending debounce)
    if (renderTimer) clearTimeout(renderTimer)
    renderMarkdown()
    // Show action buttons
    buildActionButtons()
    updateWindowSize()
  }

  function showError (message, retryCallback) {
    if (!errorBanner) return
    errorBanner.style.display = 'flex'
    errorBanner.innerHTML = ''

    const icon = document.createTextNode('⚠️ ' + message + ' ')
    errorBanner.appendChild(icon)

    if (retryCallback) {
      const retryBtn = document.createElement('span')
      retryBtn.className = 'retry-btn'
      retryBtn.textContent = 'Retry'
      retryBtn.addEventListener('click', () => {
        errorBanner.style.display = 'none'
        retryCallback()
      })
      errorBanner.appendChild(retryBtn)
    }
    updateWindowSize()
  }

  function showDisconnected (partialText, retryCallback) {
    // Keep partial content visible
    if (partialText && contentArea) {
      accumulatedText = partialText
      renderMarkdown()
    }
    streaming = false
    showError('Connection lost — partial response.', retryCallback)
  }

  function hide () {
    dropdown.classList.remove('visible')
    visible = false
    streaming = false
    accumulatedText = ''
    currentQuery = ''
    if (renderTimer) clearTimeout(renderTimer)
    dropdown.innerHTML = ''
    toolStatusBar = null
    contentArea = null
    errorBanner = null
    actionsBar = null
    expandMenu = null
    loadingIndicator = null
    document.removeEventListener('click', closeExpandMenu)
    updateWindowSize()
  }

  function isVisible () {
    return visible
  }

  function showToolStatus (toolName, status) {
    if (!toolStatusBar) return
    toolStatusBar.style.display = 'flex'

    // Check if pill for this tool already exists
    let pill = toolStatusBar.querySelector(`[data-tool="${toolName}"]`)
    if (!pill) {
      pill = document.createElement('span')
      pill.className = 'tool-status-pill'
      pill.dataset.tool = toolName
      toolStatusBar.appendChild(pill)
    }

    if (status === 'running') {
      pill.className = 'tool-status-pill running'
      pill.textContent = toolName + ' ⏳'
    } else if (status === 'done') {
      pill.className = 'tool-status-pill done'
      pill.textContent = toolName + ' ✓'
    }
    updateWindowSize()
  }

  // ── IPC listeners for streaming data from main process ──
  api.on('popbar:stream-chunk', (data) => {
    if (data && data.text) {
      appendChunk(data.text)
    }
  })

  api.on('popbar:stream-done', () => {
    finishStreaming()
  })

  api.on('popbar:stream-error', (data) => {
    const msg = (data && data.message) || 'An error occurred'
    streaming = false
    showError(msg)
  })

  api.on('popbar:tool-status', (data) => {
    if (data && data.toolName) {
      showToolStatus(data.toolName, data.status)
    }
  })

  // ── Memory form ──

  /** Currently saving text (for Quick Save result handling) */
  let memorySaveText = ''

  function showMemoryForm (text) {
    buildDropdownDOM()
    memorySaveText = text

    // Replace content area with memory form
    contentArea.innerHTML = ''
    const form = document.createElement('div')
    form.className = 'dropdown-memory-form'

    // Text preview
    const preview = document.createElement('div')
    preview.className = 'memory-text-preview'
    preview.textContent = text.length > 500 ? text.substring(0, 500) + '…' : text
    form.appendChild(preview)

    // Action buttons
    const actions = document.createElement('div')
    actions.className = 'memory-actions'

    const quickSaveBtn = document.createElement('button')
    quickSaveBtn.className = 'dropdown-btn dropdown-btn-primary'
    quickSaveBtn.textContent = 'Quick Save'
    quickSaveBtn.addEventListener('click', () => {
      quickSaveBtn.disabled = true
      quickSaveBtn.textContent = 'Saving…'
      api.send('popbar:memory-quick-save', { text })
    })
    actions.appendChild(quickSaveBtn)

    const reviewBtn = document.createElement('button')
    reviewBtn.className = 'dropdown-btn'
    reviewBtn.textContent = 'Review & Edit'
    reviewBtn.addEventListener('click', () => {
      api.send('popbar:memory-review', { text })
    })
    actions.appendChild(reviewBtn)

    const extractBtn = document.createElement('button')
    extractBtn.className = 'dropdown-btn'
    extractBtn.textContent = 'Extract Multiple'
    extractBtn.addEventListener('click', () => {
      api.send('popbar:memory-extract', { text })
    })
    actions.appendChild(extractBtn)

    form.appendChild(actions)
    contentArea.appendChild(form)

    // Show the dropdown
    dropdown.classList.add('visible')
    visible = true
    updateWindowSize()
  }

  function handleMemorySaveResult (data) {
    if (!contentArea) return
    // Find or create status element
    let status = contentArea.querySelector('.memory-save-status')
    if (!status) {
      status = document.createElement('div')
      status.className = 'memory-save-status'
      contentArea.appendChild(status)
    }

    const quickSaveBtn = contentArea.querySelector('.dropdown-btn-primary')

    if (data.success) {
      status.classList.remove('error')
      status.textContent = `Saved ✓ (Claim #${data.claimNumber || data.claimId || ''})`
      if (quickSaveBtn) {
        quickSaveBtn.textContent = 'Saved ✓'
        quickSaveBtn.disabled = true
      }
    } else {
      status.classList.add('error')
      status.textContent = data.error || 'Save failed'
      if (quickSaveBtn) {
        quickSaveBtn.textContent = 'Quick Save'
        quickSaveBtn.disabled = false
      }
    }
    updateWindowSize()
  }

  // ── Search results (M7.1 rich cards + M7.2 filters) ──

  /** Parse meta_json safely */
  function parseMeta (metaJson) {
    if (!metaJson) return {}
    try { return typeof metaJson === 'string' ? JSON.parse(metaJson) : metaJson } catch (_) { return {} }
  }

  /** Build a single rich result card */
  function buildResultCard (result) {
    const claim = result.claim || {}
    const meta = parseMeta(claim.meta_json)
    const tags = meta.tags || []

    const card = document.createElement('div')
    card.className = 'memory-result-card' + (result.is_contested ? ' result-contested' : '')

    // Row 1: friendly_id + score bar + contested icon
    const header = document.createElement('div')
    header.className = 'result-header'

    if (claim.friendly_id) {
      const fid = document.createElement('span')
      fid.className = 'result-friendly-id'
      fid.textContent = '@' + claim.friendly_id
      header.appendChild(fid)
    }

    const scoreContainer = document.createElement('div')
    scoreContainer.className = 'result-score-bar-container'
    const scoreBar = document.createElement('div')
    scoreBar.className = 'result-score-bar'
    scoreBar.style.width = Math.round((result.score || 0) * 100) + '%'
    scoreContainer.appendChild(scoreBar)
    header.appendChild(scoreContainer)

    if (result.is_contested) {
      const warn = document.createElement('span')
      warn.className = 'result-contested-icon'
      warn.textContent = '⚠'
      warn.title = 'Contested claim'
      header.appendChild(warn)
    }

    card.appendChild(header)

    // Row 2: statement
    const stmt = document.createElement('div')
    stmt.className = 'result-statement'
    stmt.textContent = claim.statement || ''
    card.appendChild(stmt)

    // Row 3: meta row
    const metaRow = document.createElement('div')
    metaRow.className = 'result-meta'

    if (claim.claim_type) {
      const badge = document.createElement('span')
      badge.className = 'result-type-badge'
      badge.textContent = claim.claim_type
      metaRow.appendChild(badge)
    }

    if (claim.context_domain) {
      const domain = document.createElement('span')
      domain.className = 'result-domain'
      domain.textContent = claim.context_domain
      metaRow.appendChild(domain)
    }

    if (tags.length > 0) {
      const tagsContainer = document.createElement('span')
      tagsContainer.className = 'result-tags'
      for (const tag of tags) {
        const pill = document.createElement('span')
        pill.className = 'result-tag'
        pill.textContent = tag
        tagsContainer.appendChild(pill)
      }
      metaRow.appendChild(tagsContainer)
    }

    card.appendChild(metaRow)

    // Row 4: action buttons
    const actions = document.createElement('div')
    actions.className = 'result-actions'

    // Pin button
    const pinBtn = document.createElement('button')
    pinBtn.textContent = '📌 Pin'
    pinBtn.addEventListener('click', (e) => {
      e.stopPropagation()
      const isPinned = pinBtn.classList.toggle('pinned')
      pinBtn.textContent = isPinned ? '📌 Pinned' : '📌 Pin'
      api.invoke('popbar:pkb-pin', { claimId: claim.claim_id, pin: isPinned })
    })
    actions.appendChild(pinBtn)

    // Edit in PKB button
    const editBtn = document.createElement('button')
    editBtn.textContent = '✏️ Edit in PKB'
    editBtn.addEventListener('click', (e) => {
      e.stopPropagation()
      api.send('popbar:memory-review', { text: claim.statement, claimId: claim.claim_id })
    })
    actions.appendChild(editBtn)

    // Use in Chat button
    const chatBtn = document.createElement('button')
    chatBtn.className = 'btn-use-in-chat'
    chatBtn.textContent = '💬 Use in Chat'
    chatBtn.addEventListener('click', (e) => {
      e.stopPropagation()
      api.send('popbar:pkb-use-in-chat', { friendlyId: claim.friendly_id, statement: claim.statement })
      chatBtn.textContent = '✓ Injected'
      setTimeout(() => { chatBtn.textContent = '💬 Use in Chat' }, 1500)
    })
    actions.appendChild(chatBtn)

    card.appendChild(actions)
    return card
  }

  /** Build filter bar from results */
  function buildFilterBar (allResults, activeFilters, onFilterChange) {
    const bar = document.createElement('div')
    bar.className = 'search-filter-bar'

    // Collect unique claim_types and context_domains
    const types = new Set()
    const domains = new Set()
    for (const r of allResults) {
      if (r.claim && r.claim.claim_type) types.add(r.claim.claim_type)
      if (r.claim && r.claim.context_domain) domains.add(r.claim.context_domain)
    }

    if (types.size > 1) {
      const label = document.createElement('span')
      label.className = 'filter-label'
      label.textContent = 'Type:'
      bar.appendChild(label)
      for (const t of types) {
        const pill = document.createElement('button')
        pill.className = 'filter-pill' + (activeFilters.claim_type === t ? ' active' : '')
        pill.textContent = t
        pill.addEventListener('click', () => {
          onFilterChange({ ...activeFilters, claim_type: activeFilters.claim_type === t ? null : t })
        })
        bar.appendChild(pill)
      }
    }

    if (domains.size > 1) {
      const label = document.createElement('span')
      label.className = 'filter-label'
      label.textContent = 'Domain:'
      bar.appendChild(label)
      for (const d of domains) {
        const pill = document.createElement('button')
        pill.className = 'filter-pill' + (activeFilters.context_domain === d ? ' active' : '')
        pill.textContent = d
        pill.addEventListener('click', () => {
          onFilterChange({ ...activeFilters, context_domain: activeFilters.context_domain === d ? null : d })
        })
        bar.appendChild(pill)
      }
    }

    // Clear button (only if any filter is active)
    if (activeFilters.claim_type || activeFilters.context_domain) {
      const clearBtn = document.createElement('button')
      clearBtn.className = 'filter-clear'
      clearBtn.textContent = '✕ Clear'
      clearBtn.addEventListener('click', () => onFilterChange({ claim_type: null, context_domain: null }))
      bar.appendChild(clearBtn)

      // Refine button — re-search with server-side filters
      const refineBtn = document.createElement('button')
      refineBtn.className = 'filter-refine'
      refineBtn.textContent = '↻ Refine'
      refineBtn.addEventListener('click', () => {
        const filters = {}
        if (activeFilters.claim_type) filters.claim_type = activeFilters.claim_type
        if (activeFilters.context_domain) filters.context_domain = activeFilters.context_domain
        api.send('popbar:action', { action: 'memory-search', text: currentQuery, filters })
      })
      bar.appendChild(refineBtn)
    }

    return bar
  }

  /** Apply client-side filters to results */
  function applyFilters (results, filters) {
    return results.filter(r => {
      if (filters.claim_type && r.claim && r.claim.claim_type !== filters.claim_type) return false
      if (filters.context_domain && r.claim && r.claim.context_domain !== filters.context_domain) return false
      return true
    })
  }

  function showSearchResults (results) {
    buildDropdownDOM()
    contentArea.innerHTML = ''

    if (!results || results.length === 0) {
      const empty = document.createElement('div')
      empty.className = 'no-results'
      empty.textContent = 'No matching memories found.'
      contentArea.appendChild(empty)
    } else {
      // State for client-side filtering
      let activeFilters = { claim_type: null, context_domain: null }

      function renderFiltered () {
        contentArea.innerHTML = ''
        const filtered = applyFilters(results, activeFilters)

        // Filter bar
        const filterBar = buildFilterBar(results, activeFilters, (newFilters) => {
          activeFilters = newFilters
          renderFiltered()
        })
        contentArea.appendChild(filterBar)

        // Result cards
        if (filtered.length === 0) {
          const empty = document.createElement('div')
          empty.className = 'no-results'
          empty.textContent = 'No results match the selected filters.'
          contentArea.appendChild(empty)
        } else {
          for (const result of filtered) {
            contentArea.appendChild(buildResultCard(result))
          }
        }
        updateWindowSize()
      }

      renderFiltered()
    }

    dropdown.classList.add('visible')
    visible = true
    updateWindowSize()
  }

  // ── Image result ──

  function showImageResult (imageData) {
    buildDropdownDOM()
    contentArea.innerHTML = ''

    const card = document.createElement('div')
    card.className = 'dropdown-image-card'

    // Image element
    const img = document.createElement('img')
    if (imageData.url) {
      img.src = imageData.url
    } else if (imageData.data) {
      img.src = `data:image/png;base64,${imageData.data}`
    } else if (imageData.image_url) {
      img.src = imageData.image_url
    }
    img.alt = 'Generated image'
    card.appendChild(img)

    // Action buttons
    const actions = document.createElement('div')
    actions.className = 'image-actions'

    const downloadBtn = document.createElement('button')
    downloadBtn.className = 'dropdown-btn dropdown-btn-primary'
    downloadBtn.textContent = 'Download'
    downloadBtn.addEventListener('click', () => {
      const a = document.createElement('a')
      a.href = img.src
      a.download = 'generated-image.png'
      a.click()
    })
    actions.appendChild(downloadBtn)

    const sidebarBtn = document.createElement('button')
    sidebarBtn.className = 'dropdown-btn'
    sidebarBtn.textContent = 'Open in Sidebar'
    sidebarBtn.addEventListener('click', () => {
      api.send('popbar:expand', { mode: 'new', query: 'Generated image', response: img.src })
    })
    actions.appendChild(sidebarBtn)

    card.appendChild(actions)
    contentArea.appendChild(card)

    dropdown.classList.add('visible')
    visible = true
    updateWindowSize()
  }

  // ── Prompt list ──

  function showPromptList (prompts) {
    buildDropdownDOM()
    contentArea.innerHTML = ''

    if (!prompts || prompts.length === 0) {
      const empty = document.createElement('div')
      empty.className = 'no-results'
      empty.textContent = 'No prompts available.'
      contentArea.appendChild(empty)
    } else {
      for (const prompt of prompts) {
        const item = document.createElement('div')
        item.className = 'prompt-list-item'

        const name = document.createTextNode(prompt.name || prompt.title || 'Untitled')
        item.appendChild(name)

        if (prompt.description) {
          const desc = document.createElement('div')
          desc.className = 'prompt-desc'
          desc.textContent = prompt.description
          item.appendChild(desc)
        }

        item.addEventListener('click', () => {
          api.send('popbar:run-prompt', { promptName: prompt.name || prompt.title, text: currentQuery })
        })

        contentArea.appendChild(item)
      }
    }

    dropdown.classList.add('visible')
    visible = true
    updateWindowSize()
  }

  // ── IPC listeners for non-LLM actions ──
  api.on('popbar:show-memory-form', (data) => { showMemoryForm(data.text) })
  api.on('popbar:show-search-results', (data) => { showSearchResults(data.results) })
  api.on('popbar:show-image-result', (data) => { showImageResult(data.imageData) })
  api.on('popbar:memory-save-result', (data) => { handleMemorySaveResult(data) })
  api.on('popbar:show-loading', (data) => { showStreaming(data.action, '', false) })

  // ── Expose API globally ──
  window.PopBarDropdown = {
    showStreaming,
    appendChunk,
    finishStreaming,
    showError,
    showDisconnected,
    hide,
    isVisible,
    showToolStatus,
    showMemoryForm,
    showSearchResults,
    showImageResult,
    showPromptList
  }

  // ── DEV: test rendering ──
  // Uncomment the block below to test the dropdown with mock streaming data
  /*
  setTimeout(() => {
    showStreaming('ask', 'What is JavaScript?', false)
    const chunks = [
      '# JavaScript\n\n',
      'JavaScript is a **dynamic**, ',
      '_interpreted_ programming language.\n\n',
      '## Code Example\n\n',
      '```javascript\nconst greet = (name) => {\n',
      '  console.log(`Hello, ${name}!`)\n',
      '}\ngreet("World")\n```\n\n',
      '> It powers the modern web.\n\n',
      '| Feature | Support |\n|---|---|\n| ES Modules | ✓ |\n| Async/Await | ✓ |\n'
    ]
    let i = 0
    const interval = setInterval(() => {
      if (i < chunks.length) {
        appendChunk(chunks[i])
        i++
      } else {
        clearInterval(interval)
        finishStreaming()
      }
    }, 200)
  }, 500)
  */

  console.log('[Dropdown] Module loaded')
})()
