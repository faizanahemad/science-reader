/**
 * preload-opencode.js — Preload script for the OpenCode tab WebContentsView.
 *
 * Exposes the `opencodeAPI` bridge for directory management, process control,
 * and status/error event listeners.
 */
import { contextBridge, ipcRenderer } from 'electron'

contextBridge.exposeInMainWorld('opencodeAPI', {
  // ── Directory management ──

  /** @returns {Promise<string[]>} Recent working directories (last 10) */
  getRecentDirs: () => ipcRenderer.invoke('opencode:get-recent-dirs'),

  /** @returns {Promise<string[]>} Pinned favorite directories */
  getPinnedDirs: () => ipcRenderer.invoke('opencode:get-pinned-dirs'),

  /** Pin a directory to favorites */
  pinDir: (dir) => ipcRenderer.invoke('opencode:pin-dir', dir),

  /** Unpin a directory from favorites */
  unpinDir: (dir) => ipcRenderer.invoke('opencode:unpin-dir', dir),

  /** Open native directory picker dialog. Returns path or null if cancelled. */
  browseDir: () => ipcRenderer.invoke('opencode:browse-dir'),

  // ── Process management ──

  /** Start opencode web in the given directory */
  start: (cwd) => ipcRenderer.invoke('opencode:start', cwd),

  /** Stop the running opencode process */
  stop: () => ipcRenderer.invoke('opencode:stop'),

  /** Restart opencode with a (potentially new) working directory */
  restart: (cwd) => ipcRenderer.invoke('opencode:restart', cwd),

  // ── Status & error events ──

  /**
   * Listen for status changes: 'starting' | 'connected' | 'disconnected' | 'error'
   * @param {(status: string) => void} callback
   */
  onStatus: (callback) => {
    ipcRenderer.on('opencode:status', (_e, status) => callback(status))
  },

  /**
   * Listen for error messages from the opencode process.
   * @param {(error: string) => void} callback
   */
  onError: (callback) => {
    ipcRenderer.on('opencode:error', (_e, error) => callback(error))
  },

  /**
   * Listen for the opencode server becoming ready.
   * @param {(port: number) => void} callback
   */
  onReady: (callback) => {
    ipcRenderer.on('opencode:ready', (_e, { port }) => callback(port))
  },

  /**
   * Remove all listeners for a given channel (cleanup).
   * @param {string} channel
   */
  removeAllListeners: (channel) => {
    const allowed = ['opencode:status', 'opencode:error', 'opencode:ready']
    if (allowed.includes(channel)) {
      ipcRenderer.removeAllListeners(channel)
    }
  }
})
