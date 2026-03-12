/**
 * main.js — Science Reader Desktop Companion entry point.
 * M1.1: Sidebar BrowserWindow with snap positions + tab bar
 * M1.2: Chat WebContentsView + Terminal WebContentsView + tab switching
 * M1.3: Session cookie sharing (auth module)
 * M1.4: Tray icon + global hotkeys
 * M1.5: OpenCode integration (WebContentsView + child process)
 * M0.5: Local filesystem MCP server
 * M3.1: PopBar floating action bar window
 * M3.3: PopBar results dropdown — clipboard, replace, expand IPC
 * M6.1: Accessibility handler — active app, window title, selected text, browser URL
 * M6.2: Screenshot capture + OCR via desktopCapturer + tesseract.js
 * M6.3: Context manager — unified context aggregation, chips, chat injection
 */
import { app, BrowserWindow, WebContentsView, Tray, Menu, globalShortcut, ipcMain, nativeImage, screen, clipboard, Notification, shell } from 'electron'
import { dirname, join, basename, extname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { readFile } from 'node:fs/promises'
import { WindowManager } from './window-manager.js'
import { PtyManager, setupTerminalIPC } from './pty-manager.js'
import { OpenCodeManager, setupOpenCodeIPC } from './opencode-manager.js'
import { startServer as startFsMcp, stopServer as stopFsMcp } from './mcp/filesystem-server.js'
import { getSessionCookie, watchAuthState } from './auth.js'
import { quickAsk, directLlmAction, expandToConversation, saveToMemoryQuick, searchMemory, generateImage, fetchPrompts, pinClaim, autocompleteMemory } from './popbar-api.js'
import { FocusManager } from './focus-manager.js'
import { ServicesHandler } from './services-handler.js'
import { AccessibilityHandler } from './accessibility-handler.js'
import { ScreenshotHandler } from './screenshot-handler.js'
import { ContextManager } from './context-manager.js'
import { PushModeManager } from './push-mode-manager.js'
import Store from 'electron-store'
import robot from '@jitsi/robotjs'

const __dirname = dirname(fileURLToPath(import.meta.url))

const SERVER_URL = 'https://assist-chat.site'
const TAB_BAR_HEIGHT = 52 // drag handle (14px) + tab bar (38px)
const OC_HEADER_HEIGHT = 44 // opencode header bar height (dir picker + status + actions)

// ── Globals ──
let sidebarWindow = null
let windowManager = null
let tray = null
let chatView = null
let terminalView = null
let opencodeView = null
let opencodeWebView = null // WebContentsView for OpenCode web UI content (below header)
const ptyManager = new PtyManager()
const openCodeManager = new OpenCodeManager()
let fsMcpHandle = null // { port, close() } from filesystem MCP server
let sidebarFocus = null
let popbarWindow = null
let popbarFocus = null
const popbarStore = new Store({ name: 'popbar-state', defaults: { 'popbar-position': null, 'popbar-tools': ['pkb_search', 'pkb_add_claim'], 'popbar-max-tool-iterations': 2 } })
const accessibilityHandler = new AccessibilityHandler()
const screenshotHandler = new ScreenshotHandler()
const contextManager = new ContextManager(accessibilityHandler, screenshotHandler)
let pushModeManager = null

// ── Tab content views (M1.2) ──

function createChatView () {
  chatView = new WebContentsView({
    webPreferences: {
      preload: join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false
    }
  })
  sidebarWindow.contentView.addChildView(chatView)
  chatView.setVisible(true) // Chat is active by default

  // Load the web UI
  chatView.webContents.loadURL(SERVER_URL)

  // Offline handling: load offline.html on navigation failure
  chatView.webContents.on('did-fail-load', (_event, errorCode, _errorDescription, validatedURL) => {
    // Ignore aborted loads (e.g. user navigated away before load finished)
    if (errorCode === -3) return
    console.warn(`[Chat] Failed to load ${validatedURL} (code ${errorCode})`)
    const offlinePath = join(__dirname, 'renderer', 'offline', 'offline.html')
    chatView.webContents.loadFile(offlinePath)
  })

  // Auth state watching (M1.3)
  watchAuthState(chatView)

  // Set initial bounds
  updateViewBounds()
}

function createTerminalView () {
  terminalView = new WebContentsView({
    webPreferences: {
      preload: join(__dirname, 'preload-terminal.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false
    }
  })
  sidebarWindow.contentView.addChildView(terminalView)
  terminalView.setVisible(false) // Hidden by default (Chat is active)

  // Load terminal HTML
  terminalView.webContents.loadFile(join(__dirname, 'renderer', 'terminal', 'terminal.html'))

  // Set initial bounds
  updateViewBounds()
}

function createOpenCodeView () {
  opencodeView = new WebContentsView({
    webPreferences: {
      preload: join(__dirname, 'preload-opencode.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false
    }
  })
  sidebarWindow.contentView.addChildView(opencodeView)
  opencodeView.setVisible(false) // Hidden by default (Chat is active)

  // Load OpenCode directory picker UI (header + controls)
  opencodeView.webContents.loadFile(join(__dirname, 'renderer', 'opencode', 'opencode.html'))

  // Set initial bounds
  updateViewBounds()
}

/**
 * Create a WebContentsView for the actual OpenCode web UI and position it below the OC header.
 * @param {number} port - The port the opencode web server is listening on
 */
function showOpenCodeWebView (port) {
  // Destroy existing one if any
  destroyOpenCodeWebView()

  opencodeWebView = new WebContentsView({
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false
    }
  })
  sidebarWindow.contentView.addChildView(opencodeWebView)

  // Block any attempt to open new windows (opencode web might try to open browser)
  opencodeWebView.webContents.setWindowOpenHandler(({ url }) => {
    console.log(`[OpenCode] Blocked window open: ${url}`)
    return { action: 'deny' }
  })

  // Match visibility to opencodeView
  opencodeWebView.setVisible(opencodeView?.isVisible() ?? false)

  // Load the OpenCode web UI
  opencodeWebView.webContents.loadURL(`http://127.0.0.1:${port}`)

  updateViewBounds()
}

/**
 * Destroy the OpenCode web content view (when stopped or on exit).
 */
function destroyOpenCodeWebView () {
  if (!opencodeWebView) return
  try {
    sidebarWindow?.contentView?.removeChildView(opencodeWebView)
    opencodeWebView.webContents?.close()
  } catch { /* already destroyed */ }
  opencodeWebView = null
}

/**
 * Update bounds for both chat and terminal views to fill the area below the tab bar.
 */
function updateViewBounds () {
  if (!sidebarWindow || sidebarWindow.isDestroyed()) return
  const [width, height] = sidebarWindow.getContentSize()
  const bounds = { x: 0, y: TAB_BAR_HEIGHT, width, height: height - TAB_BAR_HEIGHT }

  if (chatView) chatView.setBounds(bounds)
  if (terminalView) terminalView.setBounds(bounds)
  if (opencodeView) opencodeView.setBounds(bounds)

  // OpenCode web view sits below the OC header within the opencodeView area
  if (opencodeWebView) {
    const ocWebBounds = {
      x: 0,
      y: TAB_BAR_HEIGHT + OC_HEADER_HEIGHT,
      width,
      height: height - TAB_BAR_HEIGHT - OC_HEADER_HEIGHT
    }
    opencodeWebView.setBounds(ocWebBounds)
  }
}

/**
 * Switch visible tab content view.
 * @param {'chat'|'terminal'|'opencode'} tabName
 */
function switchTab (tabName) {
  if (chatView) chatView.setVisible(tabName === 'chat')
  if (terminalView) terminalView.setVisible(tabName === 'terminal')
  if (opencodeView) opencodeView.setVisible(tabName === 'opencode')
  if (opencodeWebView) opencodeWebView.setVisible(tabName === 'opencode')
}

// ── Sidebar Window (M1.1) ──

function createSidebar () {
  sidebarWindow = new BrowserWindow({
    type: 'panel',
    alwaysOnTop: true,
    level: 'floating',
    frame: false,
    transparent: false,
    show: false,
    width: 400,
    height: 800,
    webPreferences: {
      preload: join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false
    }
  })

  // Load sidebar HTML via file:// URL
  const sidebarPath = join(__dirname, 'renderer', 'sidebar', 'sidebar.html')
  sidebarWindow.loadFile(sidebarPath)

  // Window manager handles snap/position/persistence
  windowManager = new WindowManager(sidebarWindow)
  windowManager.restore()

  // Push mode manager for resizing other app windows
  pushModeManager = new PushModeManager({
    accessibilityHandler,
    windowManager,
    sidebarWindow
  })

  // M2.1: Focus state machine for sidebar
  sidebarFocus = new FocusManager({ window: sidebarWindow, name: 'sidebar' })

  // Create tab content views after sidebar is ready
  sidebarWindow.once('ready-to-show', () => {
    createChatView()
    createTerminalView()
    createOpenCodeView()
    sidebarWindow.show()
    sidebarFocus.show() // Put into hover state

    // If saved dock mode is push, activate it after window is visible
    if (windowManager.getDockMode() === 'push') {
      pushModeManager.start()
      sidebarWindow.webContents.send('sidebar:dock-mode-changed', 'push')
    }

    // Notify renderer of initial app mode
    if (windowManager.getAppMode() === 'app') {
      sidebarWindow.webContents.send('sidebar:app-mode-changed', 'app')
    }
  })

  // Save position when window moves/resizes (debounced)
  let saveTimer = null
  const debouncedSave = () => {
    if (saveTimer) clearTimeout(saveTimer)
    saveTimer = setTimeout(() => windowManager.save(), 500)
  }
  sidebarWindow.on('move', debouncedSave)
  sidebarWindow.on('resize', () => {
    debouncedSave()
    updateViewBounds()
    // Notify push mode of sidebar resize
    if (pushModeManager?.isActive()) {
      pushModeManager.onSidebarResized()
    }
  })

  sidebarWindow.on('closed', () => {
    // Stop push mode before cleanup
    pushModeManager?.stop()
    chatView = null
    terminalView = null
    opencodeView = null
    opencodeWebView = null
    sidebarWindow = null
    windowManager = null
    sidebarFocus = null
    pushModeManager = null
  })
}

function toggleSidebar () {
  if (!sidebarWindow) {
    createSidebar()
    return
  }
  sidebarFocus?.toggle()
}

// ── PopBar Window (M3.1) ──

function createPopBar () {
  const display = screen.getPrimaryDisplay()
  const { width: dw } = display.workAreaSize
  const popbarWidth = 520
  const popbarHeight = 56

  // Restore saved position or default to top-center
  let savedPos = popbarStore.get('popbar-position')
  let x, y
  if (savedPos && typeof savedPos.x === 'number' && typeof savedPos.y === 'number') {
    // Off-screen recovery: check if saved position is within any display
    const displays = screen.getAllDisplays()
    const onScreen = displays.some(d => {
      const wa = d.workArea
      return savedPos.x >= wa.x - 100 &&
        savedPos.y >= wa.y - 100 &&
        savedPos.x < wa.x + wa.width + 100 &&
        savedPos.y < wa.y + wa.height + 100
    })
    if (onScreen) {
      x = savedPos.x
      y = savedPos.y
    } else {
      // Reset to center
      x = Math.round((dw - popbarWidth) / 2)
      y = 50
    }
  } else {
    x = Math.round((dw - popbarWidth) / 2)
    y = 50
  }

  popbarWindow = new BrowserWindow({
    type: 'panel',
    alwaysOnTop: true,
    frame: false,
    transparent: true,
    show: false,
    width: popbarWidth,
    height: popbarHeight,
    x,
    y,
    resizable: false,
    minimizable: false,
    maximizable: false,
    skipTaskbar: true,
    hasShadow: true,
    webPreferences: {
      preload: join(__dirname, 'preload-popbar.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false
    }
  })

  // Load PopBar HTML
  popbarWindow.loadFile(join(__dirname, 'renderer', 'popbar', 'popbar.html'))

  // M3.1: Focus state machine with click-through
  popbarFocus = new FocusManager({ window: popbarWindow, name: 'popbar', clickThrough: true })

  popbarWindow.once('ready-to-show', () => {
    popbarWindow.show()
    popbarFocus.show() // Start in hover state
  })

  // Persist drag position (debounced)
  let popbarMoveTimer = null
  popbarWindow.on('moved', () => {
    if (popbarMoveTimer) clearTimeout(popbarMoveTimer)
    popbarMoveTimer = setTimeout(() => {
      if (popbarWindow && !popbarWindow.isDestroyed()) {
        const [px, py] = popbarWindow.getPosition()
        popbarStore.set('popbar-position', { x: px, y: py })
      }
    }, 300)
  })

  popbarWindow.on('closed', () => {
    popbarWindow = null
    popbarFocus = null
  })
}

function togglePopBar () {
  if (!popbarWindow) {
    createPopBar()
    // M6.1: Auto-grab context when PopBar is first created
    _sendPopBarContext()
    return
  }
  const wasHidden = !popbarWindow.isVisible() || popbarFocus?.state === 'hidden'
  popbarFocus?.toggle()
  // M6.1: Send context when showing PopBar
  if (wasHidden) _sendPopBarContext()
}

/**
 * M6.3: Gather unified context and send to PopBar as chips.
 * Replaces the M6.1 raw accessibility context with formatted chips.
 */
function _sendPopBarContext () {
  setTimeout(() => {
    if (!popbarWindow || popbarWindow.isDestroyed()) return
    const ctx = contextManager.gatherQuick()
    popbarWindow.webContents.send('popbar:context-update', ctx)
  }, 200)
}

// ── IPC Handlers ──

ipcMain.on('sidebar:tab-changed', (_event, tabName) => {
  console.log(`[Sidebar] Tab changed: ${tabName}`)
  switchTab(tabName)
})

ipcMain.on('sidebar:snap', (_event, mode) => {
  if (!windowManager) return
  windowManager.snap(mode)
  // Confirm snap mode back to renderer
  if (sidebarWindow && !sidebarWindow.isDestroyed()) {
    sidebarWindow.webContents.send('sidebar:snap-changed', mode)
  }
})

// Dock mode toggle: overlay ↔ push
ipcMain.on('sidebar:dock-mode', async (_event, mode) => {
  if (!windowManager) return
  if (mode !== 'overlay' && mode !== 'push') return

  windowManager.setDockMode(mode)

  if (mode === 'push') {
    if (pushModeManager && !pushModeManager.isActive()) {
      await pushModeManager.start()
    }
  } else {
    if (pushModeManager?.isActive()) {
      await pushModeManager.stop()
    }
  }

  // Confirm dock mode back to renderer
  if (sidebarWindow && !sidebarWindow.isDestroyed()) {
    sidebarWindow.webContents.send('sidebar:dock-mode-changed', mode)
  }
})

ipcMain.on('sidebar:app-mode', (_event, mode) => {
  if (!windowManager) return
  if (mode !== 'sidebar' && mode !== 'app') return

  // If switching to app mode while push mode is active, stop push mode
  if (mode === 'app' && pushModeManager?.isActive()) {
    pushModeManager.stop()
  }

  windowManager.setAppMode(mode)

  // Confirm app mode back to renderer
  if (sidebarWindow && !sidebarWindow.isDestroyed()) {
    sidebarWindow.webContents.send('sidebar:app-mode-changed', mode)
  }
})

// Manual window drag (type:'panel' ignores -webkit-app-region on macOS)
ipcMain.on('sidebar:window-drag', (_event, { dx, dy }) => {
  if (!sidebarWindow || sidebarWindow.isDestroyed()) return
  const [x, y] = sidebarWindow.getPosition()
  sidebarWindow.setPosition(x + dx, y + dy)
})

// ── Notification system ──
// Store notification references to prevent GC (click handlers would fail otherwise)
const _activeNotifications = new Set()

ipcMain.on('notification:show', (_event, payload) => {
  if (!payload || !payload.title) return
  // Check mute setting
  if (settingsStore.get('notificationsMuted', false)) return

  if (!Notification.isSupported()) return

  const notif = new Notification({
    title: payload.title,
    body: payload.body || '',
    silent: !!payload.silent
  })

  _activeNotifications.add(notif)

  notif.on('click', () => {
    // Focus + show the sidebar/app window
    if (sidebarWindow && !sidebarWindow.isDestroyed()) {
      if (sidebarWindow.isMinimized()) sidebarWindow.restore()
      sidebarWindow.show()
      sidebarWindow.focus()

      // Forward click action to the chat WebContentsView (where NotificationManager lives)
      if (chatView && !chatView.webContents.isDestroyed()) {
        chatView.webContents.send('notification:clicked', { action: payload.action || { type: 'none' } })
      }
      // Also notify sidebar renderer for tab flashing
      sidebarWindow.webContents.send('notification:clicked', { action: payload.action || { type: 'none' } })
    }
  })

  notif.on('close', () => {
    _activeNotifications.delete(notif)
  })

  notif.show()
})

// Mute setting IPC
ipcMain.handle('settings:get-notifications-muted', () => {
  return settingsStore.get('notificationsMuted', false)
})

ipcMain.handle('settings:set-notifications-muted', (_event, muted) => {
  settingsStore.set('notificationsMuted', !!muted)
  return true
})

// M1.2: Retry loading chat URL (from offline page)
ipcMain.on('chat:retry-load', () => {
  if (chatView && !chatView.webContents.isDestroyed()) {
    console.log('[Chat] Retrying load...')
    chatView.webContents.loadURL(SERVER_URL)
  }
})

// M2.1: Focus state IPC
ipcMain.on('focus:activate', () => sidebarFocus?.activate())
ipcMain.on('focus:escape', () => sidebarFocus?.handleEscape())

// M3.1: PopBar IPC
ipcMain.on('popbar:action', async (_event, payload) => {
  const { action, text, context } = payload

  // Pre-login guard
  const cookie = await getSessionCookie()
  if (!cookie) {
    if (!sidebarWindow) createSidebar()
    else sidebarWindow.show()
    if (popbarWindow && !popbarWindow.isDestroyed()) {
      popbarWindow.webContents.send('popbar:stream-error', {
        message: 'Please log in first — opening Science Reader...'
      })
    }
    return
  }

  // Helper: safe send to popbar
  const sendPopbar = (channel, data) => {
    if (popbarWindow && !popbarWindow.isDestroyed()) {
      popbarWindow.webContents.send(channel, data)
    }
  }

  if (action === 'ask') {
    // Quick Ask with tools
    const toolWhitelist = popbarStore.get('popbar-tools', ['pkb_search', 'pkb_add_claim'])
    const maxIterations = popbarStore.get('popbar-max-tool-iterations', 2)
    await quickAsk({
      text,
      context,
      tools: toolWhitelist,
      maxToolIterations: maxIterations,
      onChunk: (chunk) => sendPopbar('popbar:stream-chunk', { text: chunk }),
      onToolStatus: (toolName, status) => sendPopbar('popbar:tool-status', { toolName, status }),
      onDone: () => sendPopbar('popbar:stream-done'),
      onError: (msg) => sendPopbar('popbar:stream-error', { message: msg })
    })
  } else if (action === 'explain' || action === 'summarize') {
    // Direct LLM action (no tools)
    await directLlmAction({
      actionType: action,
      text,
      context,
      onChunk: (chunk) => sendPopbar('popbar:stream-chunk', { text: chunk }),
      onDone: () => sendPopbar('popbar:stream-done'),
      onError: (msg) => sendPopbar('popbar:stream-error', { message: msg })
    })
  } else if (action === 'memory-save') {
    // Show Quick Review form in dropdown
    sendPopbar('popbar:show-memory-form', { text })
  } else if (action === 'memory-search') {
    // Search PKB
    try {
      sendPopbar('popbar:show-loading', { action: 'memory-search' })
      const results = await searchMemory({ query: text, filters: payload.filters })
      sendPopbar('popbar:show-search-results', { results })
    } catch (err) {
      sendPopbar('popbar:stream-error', { message: err.message })
    }
  } else if (action === 'generate-image') {
    // Generate image
    try {
      sendPopbar('popbar:show-loading', { action: 'generate-image' })
      const imageData = await generateImage({ prompt: text, context })
      sendPopbar('popbar:show-image-result', { imageData })
    } catch (err) {
      sendPopbar('popbar:stream-error', { message: err.message })
    }
  } else if (action === 'context') {
    // M6.3: Gather full context and display as chips + markdown summary
    try {
      const ctx = await contextManager.gatherFull()
      sendPopbar('popbar:context-update', ctx)
      if (ctx.markdown) {
        sendPopbar('popbar:stream-chunk', { text: ctx.markdown })
        sendPopbar('popbar:stream-done', {})
      } else {
        sendPopbar('popbar:stream-chunk', { text: '_No context available. Try selecting text or opening a window._' })
        sendPopbar('popbar:stream-done', {})
      }
    } catch (err) {
      console.error('[PopBar] Context gather error:', err.message)
      sendPopbar('popbar:stream-error', { message: err.message })
    }
  } else if (action === 'screenshot') {
    // M6.2: Screenshot capture + OCR
    sendPopbar('popbar:show-loading', { message: 'Capturing screen...' })
    try {
      const result = await screenshotHandler.captureAndOCR()
      if (result) {
        sendPopbar('popbar:stream-chunk', { text: `**Screenshot captured** (${result.width}×${result.height})\n\n` })
        if (result.text) {
          sendPopbar('popbar:stream-chunk', { text: `**OCR Text:**\n\n${result.text}\n` })
        }
        sendPopbar('popbar:stream-done', {})
        // M6.3: Feed screenshot into context manager
        contextManager.setScreenshot(result)
        const ctx = contextManager.gatherQuick()
        sendPopbar('popbar:context-update', ctx)
      } else {
        sendPopbar('popbar:stream-error', { message: 'Screenshot capture failed' })
      }
    } catch (err) {
      console.error('[PopBar] Screenshot error:', err.message)
      sendPopbar('popbar:stream-error', { message: err.message })
    }
  } else {
    console.log(`[PopBar] Action '${action}' not yet implemented`)
  }
})

ipcMain.on('popbar:activate', () => popbarFocus?.activate())
ipcMain.on('popbar:escape', () => popbarFocus?.handleEscape())
ipcMain.on('popbar:resize', (_event, { width, height }) => {
  if (popbarWindow && !popbarWindow.isDestroyed()) {
    popbarWindow.setSize(width, height)
  }
})

// M3.3: PopBar dropdown IPC — Copy, Replace, Expand
ipcMain.on('popbar:copy', (_event, { text }) => {
  clipboard.writeText(text)
  console.log('[PopBar] Copied to clipboard')
})

ipcMain.on('popbar:replace', (_event, { text }) => {
  const originalClipboard = clipboard.readText()
  clipboard.writeText(text)
  // Simulate Cmd+V to paste into the focused app
  robot.keyTap('v', 'command')
  // Restore original clipboard after a short delay
  setTimeout(() => clipboard.writeText(originalClipboard), 200)
  console.log('[PopBar] Replace via paste')
})

ipcMain.on('popbar:expand', async (_event, { mode, query, response }) => {
  console.log(`[PopBar] Expand: mode=${mode}, query=${query?.substring(0, 50)}`)
  const result = await expandToConversation({ mode, query, response })
  if (result.conversationId) {
    console.log(`[PopBar] Expanded to conversation ${result.conversationId}`)
  }
  // Show sidebar with chat tab
  if (!sidebarWindow) createSidebar()
  else {
    sidebarWindow.show()
    switchTab('chat')
  }
})

// M3.5: PopBar memory action IPC handlers
ipcMain.on('popbar:memory-quick-save', async (_event, { text }) => {
  const sendPopbar = (channel, data) => {
    if (popbarWindow && !popbarWindow.isDestroyed()) {
      popbarWindow.webContents.send(channel, data)
    }
  }
  try {
    const result = await saveToMemoryQuick({ text })
    sendPopbar('popbar:memory-save-result', result)
  } catch (err) {
    sendPopbar('popbar:memory-save-result', { success: false, error: err.message })
  }
})

ipcMain.on('popbar:memory-review', (_event, { text }) => {
  // Open sidebar + PKB modal via desktopBridge
  if (!sidebarWindow) createSidebar()
  else sidebarWindow.show()
  switchTab('chat')
  // Wait for chatView to be ready, then send bridge message
  setTimeout(() => {
    if (chatView && !chatView.webContents.isDestroyed()) {
      chatView.webContents.send('bridge:open-pkb-modal', { text })
    }
  }, 300)
})

ipcMain.on('popbar:memory-extract', (_event, { text }) => {
  if (!sidebarWindow) createSidebar()
  else sidebarWindow.show()
  switchTab('chat')
  setTimeout(() => {
    if (chatView && !chatView.webContents.isDestroyed()) {
      chatView.webContents.send('bridge:open-pkb-ingest', { text })
    }
  }, 300)
})

// M7.3: PKB pin claim
ipcMain.handle('popbar:pkb-pin', async (_event, { claimId, pin }) => {
  return pinClaim({ claimId, pin })
})

// M7.4: PKB autocomplete
ipcMain.handle('popbar:pkb-autocomplete', async (_event, { query }) => {
  return autocompleteMemory({ query })
})

// M7.3: PKB use in chat — inject @friendly_id into chat input
ipcMain.on('popbar:pkb-use-in-chat', (_event, { friendlyId, statement }) => {
  if (chatView && !chatView.webContents.isDestroyed()) {
    chatView.webContents.send('bridge:fill-chat-input', { text: `@${friendlyId} ` })
  }
})

// M4.1: Shared file-drop handler — reads file and forwards to chatView
async function handleFileDrop (filePath) {
  try {
    // Ensure sidebar is visible with chat tab
    if (!sidebarWindow) createSidebar()
    else sidebarWindow.show()
    switchTab('chat')

    // Read file and forward to chatView
    const buffer = await readFile(filePath)
    const name = basename(filePath)
    const ext = extname(filePath).toLowerCase()
    const mimeTypes = {
      '.pdf': 'application/pdf',
      '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      '.doc': 'application/msword',
      '.txt': 'text/plain',
      '.md': 'text/markdown',
      '.csv': 'text/csv',
      '.png': 'image/png',
      '.jpg': 'image/jpeg',
      '.jpeg': 'image/jpeg',
      '.webp': 'image/webp',
      '.json': 'application/json',
      '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    }
    const type = mimeTypes[ext] || 'application/octet-stream'
    const base64 = buffer.toString('base64')

    setTimeout(() => {
      if (chatView && !chatView.webContents.isDestroyed()) {
        chatView.webContents.send('bridge:open-global-docs', { name, type, base64 })
      }
    }, 300)

    // Show notification
    if (Notification.isSupported()) {
      new Notification({ title: 'Science Reader', body: `Adding "${name}" to Global Docs...` }).show()
    }
  } catch (err) {
    console.error('[File Drop] Error reading file:', err.message)
    if (Notification.isSupported()) {
      new Notification({ title: 'Science Reader', body: `Failed to read file: ${err.message}` }).show()
    }
  }
}

// M4.1: File drop from sidebar tab bar
ipcMain.on('file-drop:open-global-docs', async (_event, { filePath }) => {
  await handleFileDrop(filePath)
})

// M4.1: File drop from PopBar
ipcMain.on('popbar:file-drop', async (_event, { filePath }) => {
  await handleFileDrop(filePath)
})

// M6.1: Accessibility IPC handlers
ipcMain.handle('accessibility:get-context', (_event, { level } = {}) => {
  return accessibilityHandler.getContext(level || 'basic')
})

ipcMain.handle('accessibility:get-active-app', () => {
  return accessibilityHandler.getActiveApp()
})

ipcMain.handle('accessibility:get-selected-text', () => {
  return accessibilityHandler.getSelectedText()
})

ipcMain.handle('accessibility:get-window-title', () => {
  return accessibilityHandler.getWindowTitle()
})

ipcMain.handle('accessibility:get-browser-url', () => {
  return accessibilityHandler.getBrowserURL()
})

ipcMain.handle('accessibility:get-finder-selection', () => {
  return accessibilityHandler.getFinderSelection()
})

ipcMain.handle('accessibility:is-enabled', () => {
  return accessibilityHandler.isAccessibilityEnabled()
})

ipcMain.handle('accessibility:request-access', () => {
  const granted = accessibilityHandler.isAccessibilityEnabled()
  if (!granted) {
    shell.openExternal('x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility')
  }
  return granted
})

// ── Settings IPC handlers ──

const settingsStore = new Store({
  name: 'sidebar-settings',
  defaults: {
    opencodeCustomConfig: '',
    opencodeEnvVars: {}
  }
})

ipcMain.handle('settings:get-opencode-config', () => {
  const defaultConfig = openCodeManager.getDefaultConfig()
  const customConfig = settingsStore.get('opencodeCustomConfig', '')
  return { defaultConfig, customConfig }
})

ipcMain.handle('settings:set-opencode-config', (_event, configJson) => {
  settingsStore.set('opencodeCustomConfig', configJson || '')
  return true
})

ipcMain.handle('settings:get-env-vars', () => {
  return settingsStore.get('opencodeEnvVars', {})
})

ipcMain.handle('settings:set-env-vars', (_event, vars) => {
  settingsStore.set('opencodeEnvVars', vars || {})
  return true
})

// M6.2: Screenshot IPC handlers
ipcMain.handle('screenshot:capture-screen', async () => {
  return screenshotHandler.captureScreen()
})

ipcMain.handle('screenshot:capture-window', async (_event, { sourceId }) => {
  return screenshotHandler.captureWindow(sourceId)
})

ipcMain.handle('screenshot:capture-and-ocr', async (_event, opts = {}) => {
  return screenshotHandler.captureAndOCR(opts)
})

ipcMain.handle('screenshot:list-sources', async () => {
  return screenshotHandler.listSources()
})

ipcMain.handle('screenshot:run-ocr', async (_event, { imagePath }) => {
  return screenshotHandler.runOCR(imagePath)
})

// M6.3: Context IPC handlers
ipcMain.handle('context:get-full', async () => {
  return contextManager.gatherFull()
})

ipcMain.handle('context:get-quick', () => {
  return contextManager.gatherQuick()
})

ipcMain.handle('context:add-manual', (_event, { label, value }) => {
  contextManager.addManualContext(label, value)
  return { ok: true }
})

ipcMain.handle('context:remove-manual', (_event, { label }) => {
  contextManager.removeManualContext(label)
  return { ok: true }
})

ipcMain.handle('context:clear', () => {
  contextManager.clearTransient()
  return { ok: true }
})

ipcMain.handle('context:inject-chat', async () => {
  // Gather full context and inject as markdown into chat input
  const ctx = await contextManager.gatherFull()
  if (ctx.markdown && chatView && !chatView.webContents.isDestroyed()) {
    chatView.webContents.send('bridge:fill-chat-input', { text: ctx.markdown })
    return { ok: true, markdown: ctx.markdown }
  }
  return { ok: false, reason: 'No context or chat view unavailable' }
})

// M1.6: Terminal PTY IPC
setupTerminalIPC(ipcMain, ptyManager)

// M1.5: OpenCode IPC (registered after sidebar is created, needs window ref for dialogs)
// Moved into app.whenReady() — see below

// ── Tray (M1.4) ──

function createTray () {
  const iconPath = join(__dirname, '..', 'build', 'tray-iconTemplate.png')
  const icon = nativeImage.createFromPath(iconPath)
  tray = new Tray(icon)
  tray.setToolTip('Science Reader')

  const contextMenu = Menu.buildFromTemplate([
    {
      label: 'Show/Hide Sidebar',
      click: () => toggleSidebar()
    },
    {
      label: 'Show/Hide PopBar',
      click: () => togglePopBar()
    },
    { type: 'separator' },
    {
      label: 'Start Dictation',
      click: () => console.log('[Tray] Start Dictation — placeholder')
    },
    {
      label: 'Capture Screen',
      click: () => console.log('[Tray] Capture Screen — placeholder')
    },
    { type: 'separator' },
    {
      label: 'Status: Connected ✓',
      enabled: false
    },
    {
      label: 'Settings...',
      click: () => console.log('[Tray] Settings — placeholder')
    },
    { type: 'separator' },
    {
      label: 'Quit',
      click: () => app.quit()
    }
  ])

  tray.setContextMenu(contextMenu)
}

// ── Global Hotkeys (M1.4) ──

function registerHotkeys () {
  const shortcuts = [
    {
      accelerator: 'CommandOrControl+Shift+Space',
      label: 'Toggle PopBar',
      handler: () => togglePopBar()
    },
    {
      accelerator: 'CommandOrControl+Shift+J',
      label: 'Toggle Sidebar',
      handler: () => toggleSidebar()
    },
    {
      accelerator: 'CommandOrControl+J',
      label: 'Toggle Dictation',
      handler: () => console.log('[Hotkey] Toggle Dictation — placeholder')
    },
    {
      accelerator: 'CommandOrControl+Shift+S',
      label: 'Capture Screenshot',
      handler: async () => {
        const result = await screenshotHandler.captureAndOCR()
        if (result) {
          // M6.3: Feed screenshot into context manager
          contextManager.setScreenshot(result)
          if (!popbarWindow) createPopBar()
          else popbarFocus?.activate()
          setTimeout(() => {
            const sendPopbar = (ch, d) => { if (popbarWindow && !popbarWindow.isDestroyed()) popbarWindow.webContents.send(ch, d) }
            const ctx = contextManager.gatherQuick()
            sendPopbar('popbar:context-update', ctx)
            if (result.text) {
              sendPopbar('popbar:prefill-input', { text: result.text })
            }
          }, 300)
          new Notification({ title: 'Screenshot Captured', body: result.text ? `OCR: ${result.text.slice(0, 100)}...` : `${result.width}×${result.height}` }).show()
        }
      }
    },
    {
      accelerator: 'CommandOrControl+Shift+M',
      label: 'Save to Memory',
      handler: () => {
        // M6.1: Grab selected text via accessibility and send to PopBar memory form
        const text = accessibilityHandler.getSelectedText()
        if (!popbarWindow) createPopBar()
        else popbarFocus?.activate()
        setTimeout(() => {
          const sendPopbar = (ch, d) => { if (popbarWindow && !popbarWindow.isDestroyed()) popbarWindow.webContents.send(ch, d) }
          sendPopbar('popbar:show-memory-form', { text: text || '' })
        }, 300)
      }
    }
  ]

  for (const { accelerator, label, handler } of shortcuts) {
    const ok = globalShortcut.register(accelerator, handler)
    if (!ok) {
      console.warn(`[Hotkey] Failed to register: ${label} (${accelerator})`)
    }
  }
}

// ── App lifecycle ──

app.whenReady().then(async () => {
  createSidebar()
  createTray()
  registerHotkeys()

  // M1.5: OpenCode IPC (needs sidebarWindow for dialog.showOpenDialog)
  setupOpenCodeIPC(ipcMain, openCodeManager, sidebarWindow, {
    onShowWebView: (port) => showOpenCodeWebView(port),
    onDestroyWebView: () => destroyOpenCodeWebView()
  })

  // Start local filesystem MCP server (M0.5) with home directory as default
  try {
    const defaultCwd = process.env.HOME || '/'
    fsMcpHandle = await startFsMcp(defaultCwd)
    console.log(`[MCP FS] Started on port ${fsMcpHandle.port}`)
  } catch (err) {
    console.error('[MCP FS] Failed to start:', err.message)
  }

  // M5: macOS Services handler
  const servicesHandler = new ServicesHandler()
  servicesHandler.start()

  // M6.1: Accessibility handler
  accessibilityHandler.load()
  if (!accessibilityHandler.isAccessibilityEnabled()) {
    console.warn('[Accessibility] Permission not granted — opening System Settings')
    shell.openExternal('x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility')
  }

  servicesHandler.on('saveToMemory', (text) => {
    if (!popbarWindow) createPopBar()
    else popbarFocus?.activate()
    setTimeout(() => {
      const sendPopbar = (ch, d) => { if (popbarWindow && !popbarWindow.isDestroyed()) popbarWindow.webContents.send(ch, d) }
      sendPopbar('popbar:show-memory-form', { text })
    }, 300)
  })

  servicesHandler.on('askAboutThis', (text) => {
    if (!popbarWindow) createPopBar()
    else popbarFocus?.activate()
    setTimeout(() => {
      if (popbarWindow && !popbarWindow.isDestroyed()) {
        popbarWindow.webContents.send('popbar:prefill-input', { text, action: 'ask' })
      }
    }, 300)
  })

  servicesHandler.on('explain', async (text) => {
    if (!popbarWindow) createPopBar()
    else popbarFocus?.activate()
    setTimeout(async () => {
      const cookie = await getSessionCookie()
      if (!cookie) {
        if (!sidebarWindow) createSidebar()
        return
      }
      const sendPopbar = (ch, d) => { if (popbarWindow && !popbarWindow.isDestroyed()) popbarWindow.webContents.send(ch, d) }
      sendPopbar('popbar:show-loading', { action: 'explain' })
      await directLlmAction({
        actionType: 'explain', text, context: null,
        onChunk: (chunk) => sendPopbar('popbar:stream-chunk', { text: chunk }),
        onDone: () => sendPopbar('popbar:stream-done'),
        onError: (msg) => sendPopbar('popbar:stream-error', { message: msg })
      })
    }, 300)
  })

  servicesHandler.on('summarize', async (text) => {
    if (!popbarWindow) createPopBar()
    else popbarFocus?.activate()
    setTimeout(async () => {
      const cookie = await getSessionCookie()
      if (!cookie) {
        if (!sidebarWindow) createSidebar()
        return
      }
      const sendPopbar = (ch, d) => { if (popbarWindow && !popbarWindow.isDestroyed()) popbarWindow.webContents.send(ch, d) }
      sendPopbar('popbar:show-loading', { action: 'summarize' })
      await directLlmAction({
        actionType: 'summarize', text, context: null,
        onChunk: (chunk) => sendPopbar('popbar:stream-chunk', { text: chunk }),
        onDone: () => sendPopbar('popbar:stream-done'),
        onError: (msg) => sendPopbar('popbar:stream-error', { message: msg })
      })
    }, 300)
  })

  servicesHandler.on('sendToChat', (text) => {
    if (!sidebarWindow) createSidebar()
    else sidebarWindow.show()
    switchTab('chat')
    setTimeout(() => {
      if (chatView && !chatView.webContents.isDestroyed()) {
        chatView.webContents.send('bridge:fill-chat-input', { text })
      }
    }, 300)
  })

  servicesHandler.on('runPrompt', (text) => {
    if (!popbarWindow) createPopBar()
    else popbarFocus?.activate()
    setTimeout(() => {
      if (popbarWindow && !popbarWindow.isDestroyed()) {
        popbarWindow.webContents.send('popbar:prefill-input', { text, action: 'run-prompt' })
      }
    }, 300)
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})

app.on('activate', () => {
  if (!sidebarWindow || sidebarWindow.isDestroyed()) {
    createSidebar()
  } else if (!sidebarWindow.isVisible()) {
    sidebarWindow.show()
  }
})

app.on('will-quit', async () => {
  globalShortcut.unregisterAll()
  ptyManager.killAll()
  if (popbarWindow && !popbarWindow.isDestroyed()) popbarWindow.destroy()
  await openCodeManager.stop().catch(() => {})
  await stopFsMcp().catch(() => {})
})
