import { contextBridge, ipcRenderer } from 'electron'

/**
 * Preload script for terminal WebContentsView.
 * Exposes terminal-specific IPC methods to the renderer.
 */
contextBridge.exposeInMainWorld('terminalAPI', {
  /**
   * Create a new PTY instance.
   * @param {object} [opts] - { cwd, shell, cols, rows }
   * @returns {Promise<number>} PTY instance ID
   */
  create: (opts) => ipcRenderer.invoke('terminal:create', opts),

  /**
   * Write data to a PTY's stdin.
   * @param {number} id
   * @param {string} data
   */
  input: (id, data) => ipcRenderer.send('terminal:input', { id, data }),

  /**
   * Resize a PTY.
   * @param {number} id
   * @param {number} cols
   * @param {number} rows
   */
  resize: (id, cols, rows) => ipcRenderer.send('terminal:resize', { id, cols, rows }),

  /**
   * Close/kill a PTY instance.
   * @param {number} id
   * @returns {Promise<void>}
   */
  close: (id) => ipcRenderer.invoke('terminal:close', { id }),

  /**
   * Listen for PTY data output.
   * @param {(payload: {id: number, data: string}) => void} callback
   */
  onData: (callback) => {
    ipcRenderer.on('terminal:data', (_event, payload) => callback(payload))
  },

  /**
   * Listen for PTY exit events.
   * @param {(payload: {id: number, exitCode: number, signal: number}) => void} callback
   */
  onExit: (callback) => {
    ipcRenderer.on('terminal:exit', (_event, payload) => callback(payload))
  },
})
