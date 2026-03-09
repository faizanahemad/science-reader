/**
 * Terminal renderer module.
 * Manages xterm.js instances, tab bar, split panes, and IPC with main process PTY manager.
 */

import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import { WebLinksAddon } from '@xterm/addon-web-links'
import { SearchAddon } from '@xterm/addon-search'
import { WebglAddon } from '@xterm/addon-webgl'

// ── Catppuccin Mocha Theme ──────────────────────────────────
const THEME = {
  background: '#1e1e2e',
  foreground: '#cdd6f4',
  cursor: '#f5e0dc',
  cursorAccent: '#1e1e2e',
  selectionBackground: '#585b70',
  selectionForeground: '#cdd6f4',
  black: '#45475a',
  red: '#f38ba8',
  green: '#a6e3a1',
  yellow: '#f9e2af',
  blue: '#89b4fa',
  magenta: '#f5c2e7',
  cyan: '#94e2d5',
  white: '#bac2de',
  brightBlack: '#585b70',
  brightRed: '#f38ba8',
  brightGreen: '#a6e3a1',
  brightYellow: '#f9e2af',
  brightBlue: '#89b4fa',
  brightMagenta: '#f5c2e7',
  brightCyan: '#94e2d5',
  brightWhite: '#a6adc8',
}

const TERMINAL_OPTIONS = {
  scrollback: 5000,
  fontSize: 13,
  fontFamily: 'Menlo, Monaco, monospace',
  theme: THEME,
  allowProposedApi: true,
  cursorBlink: true,
}

const api = window.terminalAPI

// ── State ───────────────────────────────────────────────────

/** @type {Map<number, TerminalInstance>} All terminal instances by PTY id */
const instances = new Map()

/** @type {number[]} Tab ordering — list of PTY ids in tab order */
let tabOrder = []

/** @type {number|null} Currently active tab's PTY id */
let activeTabId = null

/** @type {number} Incrementing label counter */
let labelCounter = 0

/**
 * Pane tree for the active tab.
 * Each tab has its own pane tree stored in tabPaneTrees.
 * @type {Map<number, PaneNode>}
 */
const tabPaneTrees = new Map()

/** @type {number|null} The focused pane's PTY id (within the active tab) */
let focusedPaneId = null

// ── Terminal Instance ───────────────────────────────────────

class TerminalInstance {
  constructor(ptyId, label) {
    this.ptyId = ptyId
    this.label = label
    this.terminal = new Terminal(TERMINAL_OPTIONS)
    this.fitAddon = new FitAddon()
    this.searchAddon = new SearchAddon()
    this.webLinksAddon = new WebLinksAddon()
    this.webglAddon = null
    this.element = null // set when mounted
    this.searchVisible = false

    this.terminal.loadAddon(this.fitAddon)
    this.terminal.loadAddon(this.searchAddon)
    this.terminal.loadAddon(this.webLinksAddon)
  }

  mount(container) {
    this.element = container
    this.terminal.open(container)

    // Try WebGL with DOM fallback
    try {
      this.webglAddon = new WebglAddon()
      this.webglAddon.onContextLoss(() => {
        this.webglAddon?.dispose()
        this.webglAddon = null
      })
      this.terminal.loadAddon(this.webglAddon)
    } catch {
      // WebGL not available, DOM renderer used
      this.webglAddon = null
    }

    // Forward input to PTY
    this.terminal.onData((data) => {
      api.input(this.ptyId, data)
    })

    this.fit()
  }

  fit() {
    if (!this.element) return
    try {
      this.fitAddon.fit()
      const dims = this.fitAddon.proposeDimensions()
      if (dims) {
        api.resize(this.ptyId, dims.cols, dims.rows)
      }
    } catch {
      // ignore fit errors during teardown
    }
  }

  focus() {
    this.terminal.focus()
  }

  dispose() {
    this.terminal.dispose()
  }
}

// ── Pane Tree ───────────────────────────────────────────────

/**
 * @typedef {{ type: 'terminal', id: number }} PaneLeaf
 * @typedef {{ type: 'split', direction: 'horizontal'|'vertical', children: [PaneNode, PaneNode] }} PaneSplit
 * @typedef {PaneLeaf | PaneSplit} PaneNode
 */

/**
 * Find the parent of a node containing the given PTY id.
 * @returns {{ parent: PaneSplit, index: number } | null}
 */
function findParent(root, targetId, parent = null, index = -1) {
  if (root.type === 'terminal') {
    if (root.id === targetId && parent) return { parent, index }
    return null
  }
  for (let i = 0; i < root.children.length; i++) {
    const result = findParent(root.children[i], targetId, root, i)
    if (result) return result
  }
  return null
}

/** Collect all terminal IDs in a pane tree. */
function collectIds(node) {
  if (node.type === 'terminal') return [node.id]
  return [...collectIds(node.children[0]), ...collectIds(node.children[1])]
}

// ── DOM Rendering ───────────────────────────────────────────

const tabBar = document.getElementById('tab-bar')
const tabAddBtn = document.getElementById('tab-add')
const paneContainer = document.getElementById('pane-container')

function renderTabs() {
  // Remove existing tabs (keep add button)
  tabBar.querySelectorAll('.tab').forEach((el) => el.remove())

  for (const id of tabOrder) {
    const inst = instances.get(id)
    if (!inst) continue

    const tab = document.createElement('div')
    tab.className = `tab${id === activeTabId ? ' active' : ''}`
    tab.dataset.id = id
    tab.innerHTML = `
      <span class="tab-label">${inst.label}</span>
      <span class="tab-close" title="Close (⌘W)">×</span>
    `
    tab.querySelector('.tab-label').addEventListener('click', () => switchTab(id))
    tab.querySelector('.tab-close').addEventListener('click', (e) => {
      e.stopPropagation()
      closeTab(id)
    })
    tabBar.insertBefore(tab, tabAddBtn)
  }
}

/**
 * Render the pane tree for the active tab into the pane container.
 */
function renderPanes() {
  paneContainer.innerHTML = ''
  if (activeTabId === null) return

  const tree = tabPaneTrees.get(activeTabId)
  if (!tree) return

  const el = buildPaneDOM(tree)
  paneContainer.appendChild(el)

  // Mount & fit all terminals in this tree
  requestAnimationFrame(() => {
    mountTerminalsInTree(tree)
    fitAllInTree(tree)
  })
}

function buildPaneDOM(node) {
  if (node.type === 'terminal') {
    const div = document.createElement('div')
    div.className = 'pane-leaf'
    div.dataset.ptyId = node.id
    if (node.id === focusedPaneId) div.classList.add('focused')

    // Click to focus
    div.addEventListener('mousedown', () => {
      setFocusedPane(node.id)
    })

    // Search overlay
    const searchOverlay = document.createElement('div')
    searchOverlay.className = 'search-overlay'
    searchOverlay.innerHTML = `
      <input type="text" placeholder="Search…" class="search-input" />
      <button class="search-prev" title="Previous">▲</button>
      <button class="search-next" title="Next">▼</button>
      <button class="search-close" title="Close">✕</button>
    `
    div.appendChild(searchOverlay)

    // Wire search
    const input = searchOverlay.querySelector('.search-input')
    const inst = instances.get(node.id)
    if (inst) {
      input.addEventListener('input', () => inst.searchAddon.findNext(input.value))
      input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
          e.shiftKey ? inst.searchAddon.findPrevious(input.value) : inst.searchAddon.findNext(input.value)
        }
        if (e.key === 'Escape') toggleSearch(node.id)
      })
      searchOverlay.querySelector('.search-next').addEventListener('click', () => inst.searchAddon.findNext(input.value))
      searchOverlay.querySelector('.search-prev').addEventListener('click', () => inst.searchAddon.findPrevious(input.value))
      searchOverlay.querySelector('.search-close').addEventListener('click', () => toggleSearch(node.id))
    }

    return div
  }

  // Split node
  const div = document.createElement('div')
  div.className = `pane-split ${node.direction}`
  const child0 = buildPaneDOM(node.children[0])
  const child1 = buildPaneDOM(node.children[1])
  const divider = document.createElement('div')
  divider.className = 'pane-divider'

  // Divider drag resize
  setupDividerDrag(divider, child0, child1, node.direction)

  div.appendChild(child0)
  div.appendChild(divider)
  div.appendChild(child1)
  return div
}

function setupDividerDrag(divider, pane0, pane1, direction) {
  let dragging = false
  let startPos = 0
  let startSize0 = 0
  let startSize1 = 0

  divider.addEventListener('mousedown', (e) => {
    e.preventDefault()
    dragging = true
    startPos = direction === 'vertical' ? e.clientX : e.clientY
    const rect0 = pane0.getBoundingClientRect()
    const rect1 = pane1.getBoundingClientRect()
    startSize0 = direction === 'vertical' ? rect0.width : rect0.height
    startSize1 = direction === 'vertical' ? rect1.width : rect1.height
    document.body.style.cursor = direction === 'vertical' ? 'col-resize' : 'row-resize'

    const onMove = (ev) => {
      if (!dragging) return
      const currentPos = direction === 'vertical' ? ev.clientX : ev.clientY
      const delta = currentPos - startPos
      const total = startSize0 + startSize1
      const newSize0 = Math.max(50, Math.min(total - 50, startSize0 + delta))
      const newSize1 = total - newSize0
      pane0.style.flex = `${newSize0} 1 0`
      pane1.style.flex = `${newSize1} 1 0`
      fitAllVisible()
    }

    const onUp = () => {
      dragging = false
      document.body.style.cursor = ''
      document.removeEventListener('mousemove', onMove)
      document.removeEventListener('mouseup', onUp)
    }

    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
  })
}

function mountTerminalsInTree(node) {
  if (node.type === 'terminal') {
    const inst = instances.get(node.id)
    const container = paneContainer.querySelector(`[data-pty-id="${node.id}"]`)
    if (inst && container && !inst.element) {
      inst.mount(container)
    } else if (inst && container && inst.element !== container) {
      // Re-mount: terminal was already opened, need to re-open in new container
      // xterm doesn't support re-open, so we need to handle this differently
      // The terminal element is moved by xterm internally
    }
    return
  }
  mountTerminalsInTree(node.children[0])
  mountTerminalsInTree(node.children[1])
}

function fitAllInTree(node) {
  if (node.type === 'terminal') {
    instances.get(node.id)?.fit()
    return
  }
  fitAllInTree(node.children[0])
  fitAllInTree(node.children[1])
}

function fitAllVisible() {
  if (activeTabId === null) return
  const tree = tabPaneTrees.get(activeTabId)
  if (tree) fitAllInTree(tree)
}

// ── Tab Management ──────────────────────────────────────────

async function createTab() {
  labelCounter++
  const label = `Terminal ${labelCounter}`
  const ptyId = await api.create()
  const inst = new TerminalInstance(ptyId, label)
  instances.set(ptyId, inst)

  // Single-pane tree for new tab
  tabPaneTrees.set(ptyId, { type: 'terminal', id: ptyId })
  tabOrder.push(ptyId)

  switchTab(ptyId)
  return ptyId
}

function switchTab(id) {
  if (!instances.has(id)) return
  if (activeTabId === id) return

  // Detach current panes
  paneContainer.innerHTML = ''

  // Reset element refs for old tab's instances
  if (activeTabId !== null) {
    const oldTree = tabPaneTrees.get(activeTabId)
    if (oldTree) resetElements(oldTree)
  }

  activeTabId = id

  // Set focused pane to the first terminal in the tab's tree
  const tree = tabPaneTrees.get(id)
  const ids = tree ? collectIds(tree) : [id]
  focusedPaneId = ids[0]

  renderTabs()
  renderPanes()

  // Focus the first pane's terminal
  requestAnimationFrame(() => {
    instances.get(focusedPaneId)?.focus()
  })
}

function resetElements(node) {
  if (node.type === 'terminal') {
    const inst = instances.get(node.id)
    if (inst) inst.element = null
    return
  }
  resetElements(node.children[0])
  resetElements(node.children[1])
}

async function closeTab(tabId) {
  // Close all PTYs in this tab's tree
  const tree = tabPaneTrees.get(tabId)
  if (!tree) return
  const ids = collectIds(tree)

  for (const id of ids) {
    const inst = instances.get(id)
    if (inst) {
      inst.dispose()
      instances.delete(id)
    }
    await api.close(id)
  }

  tabPaneTrees.delete(tabId)
  tabOrder = tabOrder.filter((t) => t !== tabId)

  if (activeTabId === tabId) {
    activeTabId = null
    focusedPaneId = null
    if (tabOrder.length > 0) {
      switchTab(tabOrder[tabOrder.length - 1])
    } else {
      renderTabs()
      renderPanes()
    }
  } else {
    renderTabs()
  }
}

// ── Split Panes ─────────────────────────────────────────────

async function splitPane(direction) {
  if (focusedPaneId === null || activeTabId === null) return

  const newPtyId = await api.create()
  labelCounter++ // not shown in tab label, but tracks instance count
  const inst = new TerminalInstance(newPtyId, `Pane ${newPtyId}`)
  instances.set(newPtyId, inst)

  const tree = tabPaneTrees.get(activeTabId)
  if (!tree) return

  const newLeaf = { type: 'terminal', id: newPtyId }

  if (tree.type === 'terminal' && tree.id === focusedPaneId) {
    // Root is the focused terminal — replace with split
    tabPaneTrees.set(activeTabId, {
      type: 'split',
      direction,
      children: [{ type: 'terminal', id: focusedPaneId }, newLeaf],
    })
  } else {
    // Find parent of focused pane and replace
    const info = findParent(tree, focusedPaneId)
    if (info) {
      const oldChild = info.parent.children[info.index]
      info.parent.children[info.index] = {
        type: 'split',
        direction,
        children: [oldChild, newLeaf],
      }
    }
  }

  // Reset elements so they remount
  resetElements(tabPaneTrees.get(activeTabId))

  focusedPaneId = newPtyId
  renderPanes()

  requestAnimationFrame(() => {
    instances.get(newPtyId)?.focus()
  })
}

function setFocusedPane(id) {
  if (focusedPaneId === id) return
  focusedPaneId = id

  // Update focused class
  paneContainer.querySelectorAll('.pane-leaf').forEach((el) => {
    el.classList.toggle('focused', Number(el.dataset.ptyId) === id)
  })

  instances.get(id)?.focus()
}

// ── Search ──────────────────────────────────────────────────

function toggleSearch(paneId) {
  const id = paneId ?? focusedPaneId
  if (id === null) return

  const leaf = paneContainer.querySelector(`[data-pty-id="${id}"]`)
  if (!leaf) return

  const overlay = leaf.querySelector('.search-overlay')
  if (!overlay) return

  const inst = instances.get(id)
  const isVisible = overlay.classList.contains('visible')

  if (isVisible) {
    overlay.classList.remove('visible')
    inst?.searchAddon.clearDecorations()
    inst?.focus()
  } else {
    overlay.classList.add('visible')
    const input = overlay.querySelector('.search-input')
    input.focus()
    input.select()
  }
}

// ── IPC Data Handling ───────────────────────────────────────

api.onData(({ id, data }) => {
  const inst = instances.get(id)
  if (inst) inst.terminal.write(data)
})

api.onExit(({ id }) => {
  // If this PTY is in the active tab, handle its closure
  // Find which tab contains this PTY
  for (const [tabId, tree] of tabPaneTrees) {
    const ids = collectIds(tree)
    if (!ids.includes(id)) continue

    const inst = instances.get(id)
    if (inst) {
      inst.terminal.writeln('\r\n\x1b[90m[Process exited]\x1b[0m')
    }
    break
  }
})

// ── Keyboard Shortcuts ──────────────────────────────────────

document.addEventListener('keydown', (e) => {
  const isMeta = e.metaKey || e.ctrlKey

  // Cmd+N: New tab
  if (isMeta && e.key === 'n') {
    e.preventDefault()
    createTab()
    return
  }

  // Cmd+W: Close current tab
  if (isMeta && e.key === 'w') {
    e.preventDefault()
    if (activeTabId !== null) closeTab(activeTabId)
    return
  }

  // Cmd+[: Previous tab
  if (isMeta && e.key === '[') {
    e.preventDefault()
    if (tabOrder.length > 1 && activeTabId !== null) {
      const idx = tabOrder.indexOf(activeTabId)
      const prev = (idx - 1 + tabOrder.length) % tabOrder.length
      switchTab(tabOrder[prev])
    }
    return
  }

  // Cmd+]: Next tab
  if (isMeta && e.key === ']') {
    e.preventDefault()
    if (tabOrder.length > 1 && activeTabId !== null) {
      const idx = tabOrder.indexOf(activeTabId)
      const next = (idx + 1) % tabOrder.length
      switchTab(tabOrder[next])
    }
    return
  }

  // Cmd+1..9: Switch to specific tab
  if (isMeta && e.key >= '1' && e.key <= '9') {
    e.preventDefault()
    const tabIdx = parseInt(e.key) - 1
    if (tabIdx < tabOrder.length) switchTab(tabOrder[tabIdx])
    return
  }

  // Cmd+D: Vertical split
  if (e.metaKey && !e.shiftKey && e.key === 'd') {
    e.preventDefault()
    splitPane('vertical')
    return
  }

  // Cmd+Shift+D: Horizontal split
  if (e.metaKey && e.shiftKey && e.key === 'D') {
    e.preventDefault()
    splitPane('horizontal')
    return
  }

  // Cmd+K: Clear terminal
  if (isMeta && e.key === 'k') {
    e.preventDefault()
    if (focusedPaneId !== null) {
      instances.get(focusedPaneId)?.terminal.clear()
    }
    return
  }

  // Ctrl+Shift+F: Toggle search
  if (e.ctrlKey && e.shiftKey && e.key === 'F') {
    e.preventDefault()
    toggleSearch()
    return
  }

  // Cmd+C: Copy if selection exists, else pass through as Ctrl+C
  if (e.metaKey && e.key === 'c') {
    if (focusedPaneId !== null) {
      const inst = instances.get(focusedPaneId)
      if (inst && inst.terminal.hasSelection()) {
        e.preventDefault()
        navigator.clipboard.writeText(inst.terminal.getSelection())
        inst.terminal.clearSelection()
        return
      }
      // else: let xterm handle it (sends \x03 via onData)
    }
  }

  // Cmd+V: Paste
  if (e.metaKey && e.key === 'v') {
    e.preventDefault()
    if (focusedPaneId !== null) {
      navigator.clipboard.readText().then((text) => {
        api.input(focusedPaneId, text)
      })
    }
    return
  }
})

// ── Window Resize ───────────────────────────────────────────

let resizeTimer = null
window.addEventListener('resize', () => {
  clearTimeout(resizeTimer)
  resizeTimer = setTimeout(() => fitAllVisible(), 50)
})

// ResizeObserver for container size changes (e.g., sidebar toggle)
const resizeObserver = new ResizeObserver(() => {
  clearTimeout(resizeTimer)
  resizeTimer = setTimeout(() => fitAllVisible(), 50)
})
resizeObserver.observe(paneContainer)

// ── Tab Add Button ──────────────────────────────────────────

tabAddBtn.addEventListener('click', () => createTab())

// ── Init ────────────────────────────────────────────────────

createTab()
