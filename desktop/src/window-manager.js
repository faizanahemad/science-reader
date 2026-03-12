/**
 * WindowManager — manages sidebar window position, snap states, and persistence.
 * Snap modes: 'right', 'left', 'bottom', 'float'
 * Dock modes: 'overlay' (always on top), 'push' (resize frontmost app)
 * Uses electron-store for persistence across restarts.
 *
 * All modes are resizable and draggable. In snapped modes, resizing re-snaps
 * to maintain edge alignment with the user's adjusted width.
 */
import { screen } from 'electron'
import Store from 'electron-store'

const DEFAULT_SIDEBAR_WIDTH = 400
const MIN_SIDEBAR_WIDTH = 250
const MAX_SIDEBAR_WIDTH_RATIO = 0.6 // Max 60% of screen width
const SIDEBAR_BOTTOM_HEIGHT = 350
const MIN_SIDEBAR_BOTTOM_HEIGHT = 200

const DEFAULTS = {
  x: 0,
  y: 0,
  width: DEFAULT_SIDEBAR_WIDTH,
  height: 800,
  snapMode: 'right',
  dockMode: 'overlay',
  appMode: 'sidebar',
  sidebarWidth: DEFAULT_SIDEBAR_WIDTH,
  bottomHeight: SIDEBAR_BOTTOM_HEIGHT
}

export class WindowManager {
  /** @param {import('electron').BrowserWindow} win */
  constructor (win) {
    this.win = win
    this.store = new Store({
      name: 'window-state',
      defaults: { windowState: { ...DEFAULTS } }
    })
    this.snapMode = 'right'
    this.dockMode = 'overlay'
    this.appMode = 'sidebar'
    this._floatBounds = null
    this._appBounds = null
    this._sidebarWidth = DEFAULT_SIDEBAR_WIDTH
    this._bottomHeight = SIDEBAR_BOTTOM_HEIGHT
    this._resizeTimer = null
    this._isSnapping = false // Guard against resize→re-snap feedback loop

    // Track resize to re-snap and persist custom width
    this.win.on('resize', () => {
      // Ignore resize events caused by our own _applySnap
      if (this._isSnapping) return
      if (this._resizeTimer) clearTimeout(this._resizeTimer)
      this._resizeTimer = setTimeout(() => this._onResizeEnd(), 300)
    })
  }

  /** Restore saved window state or apply right-snap default. */
  restore () {
    const saved = this.store.get('windowState', { ...DEFAULTS })
    this.snapMode = saved.snapMode || 'right'
    this.dockMode = saved.dockMode || 'overlay'
    this.appMode = saved.appMode || 'sidebar'
    this._sidebarWidth = saved.sidebarWidth || DEFAULT_SIDEBAR_WIDTH
    this._bottomHeight = saved.bottomHeight || SIDEBAR_BOTTOM_HEIGHT
    this._appBounds = saved.appBounds || null

    if (this.appMode === 'app') {
      this._applyAppMode()
    } else if (this.snapMode === 'float' && this._isOnScreen(saved)) {
      this._floatBounds = { x: saved.x, y: saved.y, width: saved.width, height: saved.height }
      this.win.setBounds(this._floatBounds)
    } else if (this.snapMode === 'float') {
      this.snapMode = 'right'
      this._applySnap('right')
    } else {
      this._applySnap(this.snapMode)
    }

    // All modes are resizable and movable
    this.win.setResizable(true)
    this.win.setMovable(true)
  }

  /** Snap to a given mode. */
  snap (mode) {
    if (mode === 'float') {
      this.snapMode = 'float'
      if (this._floatBounds) {
        this.win.setBounds(this._floatBounds)
      } else {
        // Center on screen with default size
        const display = this._getPrimaryDisplay()
        const { width: dw, height: dh } = display.workArea
        const w = this._sidebarWidth
        const h = Math.round(dh * 0.7)
        this._floatBounds = {
          x: Math.round((dw - w) / 2) + display.workArea.x,
          y: Math.round((dh - h) / 2) + display.workArea.y,
          width: w,
          height: h
        }
        this.win.setBounds(this._floatBounds)
      }
    } else {
      this.snapMode = mode
      this._applySnap(mode)
    }

    // All modes are resizable and movable
    this.win.setResizable(true)
    this.win.setMovable(true)
    this.save()
  }

  /** Get/set dock mode ('overlay' or 'push'). */
  getDockMode () { return this.dockMode }

  setDockMode (mode) {
    if (mode !== 'overlay' && mode !== 'push') return
    this.dockMode = mode
    this.save()
  }

  /** Get/set app mode ('sidebar' or 'app'). */
  getAppMode () { return this.appMode }

  /**
   * Toggle between sidebar mode and app mode.
   * Sidebar: alwaysOnTop, frameless panel, narrow, snapped.
   * App: normal window, not always-on-top, traffic light buttons, larger.
   * @param {'sidebar'|'app'} mode
   */
  setAppMode (mode) {
    if (mode !== 'sidebar' && mode !== 'app') return
    if (mode === this.appMode) return

    if (mode === 'app') {
      // Save current sidebar state before switching
      this.save()
      this.appMode = 'app'
      this._applyAppMode()
    } else {
      // Save app bounds before switching back
      this._appBounds = this.win.getBounds()
      this.appMode = 'sidebar'
      this._applySidebarMode()
    }
    this.save()
  }

  /** Apply app mode: large centered window, not always-on-top, show traffic lights. */
  _applyAppMode () {
    this._isSnapping = true
    const display = this._getPrimaryDisplay()
    const { x: dx, y: dy, width: dw, height: dh } = display.workArea

    // Restore saved app bounds or center with a reasonable default size
    let bounds = this._appBounds
    if (!bounds || !this._isOnScreen(bounds)) {
      const w = Math.min(1200, Math.round(dw * 0.8))
      const h = Math.min(900, Math.round(dh * 0.85))
      bounds = {
        x: dx + Math.round((dw - w) / 2),
        y: dy + Math.round((dh - h) / 2),
        width: w,
        height: h
      }
    }

    this.win.setAlwaysOnTop(false)
    this.win.setVisibleOnAllWorkspaces(false)
    this.win.setSkipTaskbar?.(false) // Show in dock/taskbar
    if (typeof this.win.setWindowButtonVisibility === 'function') {
      this.win.setWindowButtonVisibility(true) // macOS traffic lights
    }
    this.win.setBounds(bounds)
    this.win.setResizable(true)
    this.win.setMovable(true)
    this.win.setMinimumSize(600, 400)

    setTimeout(() => { this._isSnapping = false }, 100)
  }

  /** Apply sidebar mode: narrow floating panel, always-on-top, hide traffic lights. */
  _applySidebarMode () {
    this._isSnapping = true

    this.win.setAlwaysOnTop(true, 'floating')
    this.win.setVisibleOnAllWorkspaces(true)
    if (typeof this.win.setWindowButtonVisibility === 'function') {
      this.win.setWindowButtonVisibility(false) // Hide traffic lights
    }
    this.win.setMinimumSize(MIN_SIDEBAR_WIDTH, 200)

    // Re-apply the saved snap mode
    if (this.snapMode === 'float' && this._floatBounds) {
      this.win.setBounds(this._floatBounds)
    } else {
      this._applySnap(this.snapMode)
    }

    this.win.setResizable(true)
    this.win.setMovable(true)

    setTimeout(() => { this._isSnapping = false }, 100)
  }
  getDockMode () { return this.dockMode }

  setDockMode (mode) {
    if (mode !== 'overlay' && mode !== 'push') return
    this.dockMode = mode
    this.save()
  }

  /** Save current bounds and snap mode to store. */
  save () {
    const bounds = this.win.getBounds()
    if (this.snapMode === 'float') {
      this._floatBounds = bounds
    }
    this.store.set('windowState', {
      x: bounds.x,
      y: bounds.y,
      width: bounds.width,
      height: bounds.height,
      snapMode: this.snapMode,
      dockMode: this.dockMode,
      appMode: this.appMode,
      sidebarWidth: this._sidebarWidth,
      bottomHeight: this._bottomHeight,
      appBounds: this._appBounds
    })
  }

  /** Get current snap mode. */
  getSnapMode () { return this.snapMode }

  /** Get the current sidebar width (for push mode calculations). */
  getSidebarWidth () { return this._sidebarWidth }

  /** Apply a snap position to the window. */
  _applySnap (mode) {
    this._isSnapping = true
    const display = this._getPrimaryDisplay()
    const { x: dx, y: dy, width: dw, height: dh } = display.workArea
    const maxWidth = Math.round(dw * MAX_SIDEBAR_WIDTH_RATIO)
    const w = Math.min(Math.max(this._sidebarWidth, MIN_SIDEBAR_WIDTH), maxWidth)

    let bounds
    switch (mode) {
      case 'left':
        bounds = { x: dx, y: dy, width: w, height: dh }
        break
      case 'bottom': {
        const bh = Math.min(Math.max(this._bottomHeight, MIN_SIDEBAR_BOTTOM_HEIGHT), Math.round(dh * 0.6))
        bounds = { x: dx, y: dy + dh - bh, width: dw, height: bh }
        break
      }
      case 'right':
      default:
        bounds = { x: dx + dw - w, y: dy, width: w, height: dh }
        break
    }

    this.win.setBounds(bounds)
    this.win.setResizable(true)
    this.win.setMovable(true)

    // Release the guard after a tick so the setBounds resize event is ignored
    setTimeout(() => { this._isSnapping = false }, 100)
  }

  /**
   * Called after a resize ends (debounced).
   * In snapped modes, capture the new width and re-snap to keep edge alignment.
   */
  _onResizeEnd () {
    if (this.snapMode === 'float') {
      // Float mode: just save bounds as-is
      this._floatBounds = this.win.getBounds()
      this.save()
      return
    }

    const bounds = this.win.getBounds()
    const display = this._getPrimaryDisplay()
    const { width: dw } = display.workArea
    const maxWidth = Math.round(dw * MAX_SIDEBAR_WIDTH_RATIO)

    if (this.snapMode === 'bottom') {
      // For bottom mode, track height changes
      this._bottomHeight = Math.min(Math.max(bounds.height, MIN_SIDEBAR_BOTTOM_HEIGHT), Math.round(display.workArea.height * 0.6))
    } else {
      // For left/right modes, track width changes
      this._sidebarWidth = Math.min(Math.max(bounds.width, MIN_SIDEBAR_WIDTH), maxWidth)
    }

    // Re-snap to correct edge alignment with new dimensions
    this._applySnap(this.snapMode)
    this.save()
  }

  /** Check if saved position is within any connected display. */
  _isOnScreen (saved) {
    const displays = screen.getAllDisplays()
    return displays.some(d => {
      const { x, y, width, height } = d.workArea
      return saved.x >= x - 50 &&
        saved.y >= y - 50 &&
        saved.x < x + width + 50 &&
        saved.y < y + height + 50
    })
  }

  /** Get the primary display. */
  _getPrimaryDisplay () {
    return screen.getPrimaryDisplay()
  }
}
