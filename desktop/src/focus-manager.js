/**
 * focus-manager.js — Reusable focus state machine for panel windows (M2.1).
 *
 * Three states: 'hidden', 'hover', 'active'
 *   hidden — window not visible
 *   hover  — visible but not focused (keyboard stays with underlying app)
 *   active — fully interactive, focused
 *
 * Two hover modes via `clickThrough` option:
 *   clickThrough: true  — setIgnoreMouseEvents(true, { forward: true }) + setFocusable(false)
 *                          Mouse clicks pass through. For overlays like PopBar.
 *   clickThrough: false — setFocusable(false) only. Mouse clicks work on window buttons.
 *                          For persistent surfaces like Sidebar.
 *
 * Decision 69 pattern (click-through):
 *   hover:  setIgnoreMouseEvents(true, { forward: true }) + setFocusable(false)
 *   active: setIgnoreMouseEvents(false) + setFocusable(true) + focus()
 */
export class FocusManager {
  /** @param {{ window: Electron.BrowserWindow, name: string, clickThrough?: boolean }} opts */
  constructor ({ window, name, clickThrough = false }) {
    this._win = window
    this._name = name
    this._clickThrough = clickThrough
    this._state = 'hidden'
    this._escapeTimer = null
  }

  // ── Public API ──

  /** Transition to Active from Hover. */
  activate () {
    if (this._state !== 'hover') return
    this._applyActive()
  }

  /** Transition to Hover from Active. */
  deactivate () {
    if (this._state !== 'active') return
    this._applyHover()
  }

  /** Transition to Hidden. */
  hide () {
    if (this._dead()) return
    this._win.hide()
    this._setState('hidden')
  }

  /** Transition to Hover (show window). */
  show () {
    if (this._dead()) return
    this._win.show()
    this._applyHover()
  }

  /** Toggle: hidden→show, visible→hide. */
  toggle () {
    if (this._dead()) return
    if (this._state === 'hidden') {
      this.show()
    } else {
      this.hide()
    }
  }

  /**
   * Double-Escape flow:
   *   Active → Hover (first Escape)
   *   Hover  → Hidden (second Escape within 500ms)
   */
  handleEscape () {
    if (this._state === 'active') {
      this._applyHover()
      // Arm timer — if second Escape arrives within 500ms, hide
      this._escapeTimer = setTimeout(() => {
        this._escapeTimer = null
      }, 500)
    } else if (this._state === 'hover') {
      if (this._escapeTimer) {
        clearTimeout(this._escapeTimer)
        this._escapeTimer = null
        this.hide()
      }
      // If no timer running, single Escape in hover does nothing
    }
  }

  /** @returns {'hidden'|'hover'|'active'} */
  getState () {
    return this._state
  }

  // ── Internal helpers ──

  _dead () {
    return !this._win || this._win.isDestroyed()
  }

  _setState (state) {
    this._state = state
    if (!this._dead()) {
      this._win.webContents.send('focus:state-changed', {
        name: this._name,
        state
      })
    }
  }

  _applyHover () {
    if (this._dead()) return
    if (this._clickThrough) {
      this._win.setIgnoreMouseEvents(true, { forward: true })
      this._win.setFocusable(false)
    }
    // Non-clickThrough windows (sidebar) stay focusable in hover state
    // so that clicking input fields (login, chat) takes keyboard focus.
    // Only visual dimming distinguishes hover from active.
    this._win.blur()
    this._setState('hover')
  }

  _applyActive () {
    if (this._dead()) return
    if (this._clickThrough) {
      this._win.setIgnoreMouseEvents(false)
    }
    this._win.setFocusable(true)
    this._win.focus()
    this._setState('active')
  }
}
