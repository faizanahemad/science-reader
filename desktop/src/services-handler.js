/**
 * services-handler.js — JS wrapper for the macOS Services native addon.
 * Loads the native N-API module and exposes service events to Electron main process.
 *
 * Usage:
 *   const handler = new ServicesHandler()
 *   handler.start()
 *   handler.on('saveToMemory', (text) => { ... })
 *   handler.on('*', (action, text) => { ... })
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
    return require_(join(__dirname, '..', 'native', 'services', 'build', 'Release', 'macos_services.node'))
  } catch (err) {
    console.warn('[ServicesHandler] Native addon not available:', err.message)
    return null
  }
}

export class ServicesHandler {
  constructor () {
    this._listeners = new Map() // action → Set<callback>
    this._wildcardListeners = new Set()
    this._started = false
  }

  /**
   * Register the app as a macOS Services provider.
   * Call once after app.whenReady().
   */
  start () {
    if (this._started) return

    if (!addon) addon = loadAddon()
    if (!addon) {
      console.warn('[ServicesHandler] Skipping — native addon not loaded (non-macOS or build missing)')
      return
    }

    try {
      addon.registerServicesProvider()
      addon.onServiceMessage(this._handleMessage.bind(this))
      this._started = true
      console.log('[ServicesHandler] macOS Services provider registered')
    } catch (err) {
      console.error('[ServicesHandler] Failed to start:', err.message)
    }
  }

  /**
   * Register a listener for a specific service action or '*' for all.
   * @param {string} action — 'saveToMemory' | 'askAboutThis' | 'explain' | 'summarize' | 'sendToChat' | 'runPrompt' | '*'
   * @param {Function} callback — (text: string) for specific actions, (action: string, text: string) for wildcard
   */
  on (action, callback) {
    if (action === '*') {
      this._wildcardListeners.add(callback)
      return this
    }
    if (!this._listeners.has(action)) {
      this._listeners.set(action, new Set())
    }
    this._listeners.get(action).add(callback)
    return this
  }

  /**
   * Remove a listener.
   */
  off (action, callback) {
    if (action === '*') {
      this._wildcardListeners.delete(callback)
      return this
    }
    const set = this._listeners.get(action)
    if (set) set.delete(callback)
    return this
  }

  /**
   * Internal handler called by the native addon via threadsafe function.
   * @param {string} action
   * @param {string} text
   */
  _handleMessage (action, text) {
    console.log(`[ServicesHandler] Received: action=${action}, text=${text?.substring(0, 80)}...`)

    // Dispatch to action-specific listeners
    const set = this._listeners.get(action)
    if (set) {
      for (const cb of set) {
        try { cb(text) } catch (err) {
          console.error(`[ServicesHandler] Listener error (${action}):`, err)
        }
      }
    }

    // Dispatch to wildcard listeners
    for (const cb of this._wildcardListeners) {
      try { cb(action, text) } catch (err) {
        console.error('[ServicesHandler] Wildcard listener error:', err)
      }
    }
  }
}
