/**
 * push-mode-manager.js — Manages "push" dock mode for the sidebar.
 *
 * In push mode, the sidebar docks to the right edge and the frontmost app's
 * window is resized to fill the remaining screen space (screen width − sidebar width).
 *
 * When the user switches to a different app:
 *   1. The previously pushed app's window is restored to its original bounds.
 *   2. The newly focused app's window is pushed (resized) to make room.
 *
 * Uses AppleScript (via osascript) for cross-app window manipulation and
 * the AccessibilityHandler for frontmost-app detection (polled).
 *
 * Requires: macOS, accessibility permission granted.
 */
import { execFile } from 'node:child_process'
import { app, screen } from 'electron'

const POLL_INTERVAL_MS = 750
const OSASCRIPT = '/usr/bin/osascript'

// System/utility processes that should never be pushed
const IGNORED_BUNDLE_IDS = new Set([
  'com.apple.UserNotificationCenter',
  'com.apple.notificationcenterui',
  'com.apple.controlcenter',
  'com.apple.Spotlight',
  'com.apple.dock',
  'com.apple.finder', // Finder desktop — has no meaningful window to push
  'com.apple.loginwindow',
  'com.apple.SecurityAgent',
  'com.apple.systemuiserver'
])

export class PushModeManager {
  /**
   * @param {object} opts
   * @param {import('./accessibility-handler.js').AccessibilityHandler} opts.accessibilityHandler
   * @param {import('./window-manager.js').WindowManager} opts.windowManager
   * @param {import('electron').BrowserWindow} opts.sidebarWindow
   */
  constructor ({ accessibilityHandler, windowManager, sidebarWindow }) {
    this._ax = accessibilityHandler
    this._wm = windowManager
    this._sidebarWin = sidebarWindow
    this._active = false
    this._pollTimer = null
    this._ownPid = process.pid // Our Electron process PID — never push ourselves

    // Track pushed app: { pid, bundleId, name, originalBounds: {x,y,w,h} }
    this._pushedApp = null
    // Last known frontmost PID (to detect switches)
    this._lastPid = null
    // Debounce guard for resize
    this._resizeDebounce = null
    // Lock to prevent concurrent AppleScript calls
    this._busy = false
  }

  /** Activate push mode — start monitoring and push the current frontmost app. */
  async start () {
    if (this._active) return
    if (process.platform !== 'darwin') return
    this._active = true
    console.log('[PushMode] Started')

    // Push the current frontmost app immediately
    await this._pushCurrentApp()

    // Start polling for app switches
    this._pollTimer = setInterval(() => this._poll(), POLL_INTERVAL_MS)
  }

  /** Deactivate push mode — restore any pushed app and stop monitoring. */
  async stop () {
    if (!this._active) return
    this._active = false

    if (this._pollTimer) {
      clearInterval(this._pollTimer)
      this._pollTimer = null
    }
    if (this._resizeDebounce) {
      clearTimeout(this._resizeDebounce)
      this._resizeDebounce = null
    }

    // Restore the previously pushed app
    await this._restorePushedApp()
    this._pushedApp = null
    this._lastPid = null
    console.log('[PushMode] Stopped')
  }

  /** Check if push mode is currently active. */
  isActive () { return this._active }

  /** Called when sidebar is resized — debounce and re-push the current app with new width. */
  onSidebarResized () {
    if (!this._active || !this._pushedApp) return
    if (this._resizeDebounce) clearTimeout(this._resizeDebounce)
    this._resizeDebounce = setTimeout(async () => {
      this._resizeDebounce = null
      if (!this._active || !this._pushedApp || this._busy) return
      this._busy = true
      try {
        const sidebarBounds = this._sidebarWin.getBounds()
        const display = screen.getPrimaryDisplay()
        const { x: dx, y: dy, width: dw, height: dh } = display.workArea
        const newWidth = dw - sidebarBounds.width
        if (newWidth > 200) {
          await this._setWindowBounds(this._pushedApp.name, {
            x: dx, y: dy, w: newWidth, h: dh
          })
        }
      } catch (err) {
        console.warn('[PushMode] Resize push error:', err.message)
      } finally {
        this._busy = false
      }
    }, 500)
  }

  // ── Internal ──

  /** @returns {boolean} true if this PID/bundleId should be ignored */
  _shouldIgnore (appInfo) {
    if (!appInfo || !appInfo.pid) return true
    // Never push our own Electron process
    if (appInfo.pid === this._ownPid) return true
    // Never push known system processes
    if (appInfo.bundleId && IGNORED_BUNDLE_IDS.has(appInfo.bundleId)) return true
    return false
  }

  async _poll () {
    if (!this._active || this._busy) return

    try {
      const appInfo = this._ax.getActiveApp()
      if (this._shouldIgnore(appInfo)) return

      // Detect frontmost app change
      if (appInfo.pid !== this._lastPid) {
        this._busy = true
        try {
          await this._onAppSwitched(appInfo)
        } finally {
          this._busy = false
        }
      }
    } catch (err) {
      console.warn('[PushMode] Poll error:', err.message)
    }
  }

  async _onAppSwitched (newApp) {
    this._lastPid = newApp.pid

    // 1. Restore the previously pushed app
    if (this._pushedApp && this._pushedApp.pid !== newApp.pid) {
      await this._restorePushedApp()
    }

    // 2. Push the new frontmost app
    await this._pushApp(newApp)
  }

  async _pushCurrentApp () {
    const appInfo = this._ax.getActiveApp()
    if (this._shouldIgnore(appInfo)) return
    this._lastPid = appInfo.pid
    this._busy = true
    try {
      await this._pushApp(appInfo)
    } finally {
      this._busy = false
    }
  }

  async _pushApp (appInfo) {
    try {
      // Get current window bounds before pushing
      const bounds = await this._getWindowBounds(appInfo.name)
      if (!bounds) {
        // App has no window (e.g. menu bar only) — skip silently
        return
      }

      // Store original bounds for restoration
      this._pushedApp = {
        pid: appInfo.pid,
        bundleId: appInfo.bundleId,
        name: appInfo.name,
        originalBounds: bounds
      }

      // Calculate new bounds: fill screen minus sidebar
      const sidebarBounds = this._sidebarWin.getBounds()
      const display = screen.getPrimaryDisplay()
      const { x: dx, y: dy, width: dw, height: dh } = display.workArea
      const newWidth = dw - sidebarBounds.width

      if (newWidth < 200) return // Safety: don't squish to nothing

      await this._setWindowBounds(appInfo.name, {
        x: dx, y: dy, w: newWidth, h: dh
      })

      console.log(`[PushMode] Pushed "${appInfo.name}" (pid ${appInfo.pid}) → width ${newWidth}`)
    } catch (err) {
      console.warn(`[PushMode] Failed to push "${appInfo.name}":`, err.message)
    }
  }

  async _restorePushedApp () {
    if (!this._pushedApp) return

    const { name, originalBounds, pid } = this._pushedApp
    try {
      await this._setWindowBounds(name, originalBounds)
      console.log(`[PushMode] Restored "${name}" (pid ${pid})`)
    } catch (err) {
      console.warn(`[PushMode] Failed to restore "${name}":`, err.message)
    }
    this._pushedApp = null
  }

  // ── AppleScript helpers ──

  /**
   * Get the bounds of the frontmost window of an app.
   * @param {string} appName — e.g. "Safari", "Google Chrome"
   * @returns {Promise<{x:number, y:number, w:number, h:number}|null>}
   */
  _getWindowBounds (appName) {
    return new Promise((resolve) => {
      const script = `
        tell application "System Events"
          tell process "${this._escapeAS(appName)}"
            if (count of windows) > 0 then
              set winPos to position of window 1
              set winSize to size of window 1
              return (item 1 of winPos as text) & "," & (item 2 of winPos as text) & "," & (item 1 of winSize as text) & "," & (item 2 of winSize as text)
            else
              return "none"
            end if
          end tell
        end tell
      `

      execFile(OSASCRIPT, ['-e', script], { timeout: 3000 }, (err, stdout) => {
        if (err) {
          resolve(null)
          return
        }
        const trimmed = stdout.trim()
        if (trimmed === 'none' || !trimmed) {
          resolve(null)
          return
        }
        const parts = trimmed.split(',').map(Number)
        if (parts.length !== 4 || parts.some(isNaN)) {
          resolve(null)
          return
        }
        resolve({ x: parts[0], y: parts[1], w: parts[2], h: parts[3] })
      })
    })
  }

  /**
   * Set the bounds of the frontmost window of an app.
   * @param {string} appName
   * @param {{x:number, y:number, w:number, h:number}} bounds
   * @returns {Promise<void>}
   */
  _setWindowBounds (appName, bounds) {
    return new Promise((resolve, reject) => {
      const { x, y, w, h } = bounds
      // Set position and size in a single script to reduce jitter
      const script = `
        tell application "System Events"
          tell process "${this._escapeAS(appName)}"
            if (count of windows) > 0 then
              set position of window 1 to {${Math.round(x)}, ${Math.round(y)}}
              set size of window 1 to {${Math.round(w)}, ${Math.round(h)}}
            end if
          end tell
        end tell
      `

      execFile(OSASCRIPT, ['-e', script], { timeout: 3000 }, (err) => {
        if (err) {
          reject(err)
          return
        }
        resolve()
      })
    })
  }

  /** Escape a string for safe use in AppleScript. */
  _escapeAS (str) {
    if (!str) return ''
    return str.replace(/\\/g, '\\\\').replace(/"/g, '\\"')
  }
}
