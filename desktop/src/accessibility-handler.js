/**
 * accessibility-handler.js — JS wrapper for the macOS Accessibility native addon.
 * Loads the native N-API module and exposes synchronous accessors for
 * active app info, window titles, selected text, browser URLs, etc.
 *
 * All methods are synchronous and return null/empty on failure (graceful degradation).
 * On non-macOS platforms or if the addon is missing, all methods return null/empty.
 *
 * Usage:
 *   import { AccessibilityHandler } from './accessibility-handler.js'
 *   const ax = new AccessibilityHandler()
 *   const app = ax.getActiveApp()       // { name, bundleId, pid } | null
 *   const title = ax.getWindowTitle()   // string | null
 *   const text = ax.getSelectedText()   // string | null
 */

import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))

let addon = null

function loadAddon () {
  if (process.platform !== 'darwin') return null

  try {
    const require_ = createRequire(import.meta.url)
    return require_(join(__dirname, '..', 'native', 'accessibility', 'build', 'Release', 'macos_accessibility.node'))
  } catch (err) {
    console.warn('[AccessibilityHandler] Native addon not available:', err.message)
    return null
  }
}

export class AccessibilityHandler {
  constructor () {
    this._addon = null
    this._loaded = false
  }

  /**
   * Load the native addon. Call once after app.whenReady().
   * Returns true if addon loaded successfully.
   */
  load () {
    if (this._loaded) return !!this._addon

    if (!addon) addon = loadAddon()
    this._addon = addon
    this._loaded = true

    if (this._addon) {
      console.log('[AccessibilityHandler] Native addon loaded')
    } else {
      console.warn('[AccessibilityHandler] Skipping — native addon not loaded (non-macOS or build missing)')
    }

    return !!this._addon
  }

  /**
   * Check if accessibility permission is granted.
   * @returns {boolean}
   */
  isAccessibilityEnabled () {
    if (!this._addon) return false
    try {
      return this._addon.isAccessibilityEnabled()
    } catch (err) {
      console.error('[AccessibilityHandler] isAccessibilityEnabled error:', err.message)
      return false
    }
  }

  /**
   * Prompt the user to grant accessibility permission (opens System Settings).
   * @returns {boolean} whether permission is currently granted after the prompt
   */
  requestAccessibilityAccess () {
    if (!this._addon) return false
    try {
      return this._addon.requestAccessibilityAccess()
    } catch (err) {
      console.error('[AccessibilityHandler] requestAccessibilityAccess error:', err.message)
      return false
    }
  }

  /**
   * Get the frontmost application.
   * @returns {{ name: string, bundleId: string, pid: number } | null}
   */
  getActiveApp () {
    if (!this._addon) return null
    try {
      return this._addon.getActiveApp()
    } catch (err) {
      console.error('[AccessibilityHandler] getActiveApp error:', err.message)
      return null
    }
  }

  /**
   * Get the window title of the frontmost application.
   * @returns {string | null}
   */
  getWindowTitle () {
    if (!this._addon) return null
    try {
      return this._addon.getWindowTitle()
    } catch (err) {
      console.error('[AccessibilityHandler] getWindowTitle error:', err.message)
      return null
    }
  }

  /**
   * Get the currently selected text in the frontmost application.
   * @returns {string | null}
   */
  getSelectedText () {
    if (!this._addon) return null
    try {
      return this._addon.getSelectedText()
    } catch (err) {
      console.error('[AccessibilityHandler] getSelectedText error:', err.message)
      return null
    }
  }

  /**
   * Get info about the focused UI element.
   * @returns {{ role: string, title: string, value: string } | null}
   */
  getFocusedElementInfo () {
    if (!this._addon) return null
    try {
      return this._addon.getFocusedElementInfo()
    } catch (err) {
      console.error('[AccessibilityHandler] getFocusedElementInfo error:', err.message)
      return null
    }
  }

  /**
   * Get the URL of the current tab in the frontmost browser (Safari, Chrome, Arc, Firefox).
   * @returns {string | null}
   */
  getBrowserURL () {
    if (!this._addon) return null
    try {
      return this._addon.getBrowserURL()
    } catch (err) {
      console.error('[AccessibilityHandler] getBrowserURL error:', err.message)
      return null
    }
  }

  /**
   * Get file paths of the current Finder selection.
   * @returns {string[]}
   */
  getFinderSelection () {
    if (!this._addon) return []
    try {
      return this._addon.getFinderSelection()
    } catch (err) {
      console.error('[AccessibilityHandler] getFinderSelection error:', err.message)
      return []
    }
  }

  /**
   * Get the current file path from VS Code (extracted from window title).
   * @returns {string | null}
   */
  getVSCodeFilePath () {
    if (!this._addon) return null
    try {
      return this._addon.getVSCodeFilePath()
    } catch (err) {
      console.error('[AccessibilityHandler] getVSCodeFilePath error:', err.message)
      return null
    }
  }

  /**
   * Gather full context from the active app. Combines multiple API calls
   * into a single context object suitable for LLM system prompts.
   *
   * @param {'basic' | 'text' | 'screenshot' | 'full'} level - Context depth
   * @returns {{ app: object, windowTitle: string, selectedText?: string, browserURL?: string, finderSelection?: string[], vsCodeFile?: string }}
   */
  getContext (level = 'basic') {
    const context = {
      app: this.getActiveApp(),
      windowTitle: this.getWindowTitle()
    }

    if (level === 'basic') return context

    // text level and above: add selected text + app-specific enrichment
    context.selectedText = this.getSelectedText()

    if (context.app) {
      const bundleId = context.app.bundleId || ''

      // Browser enrichment
      if (
        bundleId === 'com.apple.Safari' ||
        bundleId === 'com.google.Chrome' ||
        bundleId === 'company.thebrowser.Browser' ||
        bundleId === 'org.mozilla.firefox'
      ) {
        context.browserURL = this.getBrowserURL()
      }

      // Finder enrichment
      if (bundleId === 'com.apple.finder') {
        context.finderSelection = this.getFinderSelection()
      }

      // VS Code enrichment
      if (bundleId === 'com.microsoft.VSCode') {
        context.vsCodeFile = this.getVSCodeFilePath()
      }
    }

    // screenshot and full levels add capture data — handled by caller (main.js)
    // since screenshot capture requires desktopCapturer which is a separate module

    return context
  }
}
