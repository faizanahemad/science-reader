import pty from 'node-pty'

/**
 * Manages PTY (pseudo-terminal) instances for the desktop terminal module.
 * Each PTY is identified by a unique incrementing integer ID.
 */
export class PtyManager {
  constructor() {
    /** @type {Map<number, import('node-pty').IPty>} */
    this._ptys = new Map()
    this._nextId = 1
  }

  /**
   * Spawn a new PTY instance.
   * @param {number|null} id - Optional specific ID; if null, auto-assigns next ID.
   * @param {object} opts
   * @param {string} [opts.cwd] - Working directory for the shell.
   * @param {string} [opts.shell] - Shell executable path.
   * @param {number} [opts.cols=80] - Initial column count.
   * @param {number} [opts.rows=24] - Initial row count.
   * @returns {number} The PTY instance ID.
   */
  createPty(id, { cwd, shell, cols = 80, rows = 24 } = {}) {
    const ptyId = id ?? this._nextId++
    if (id !== null && id !== undefined && id >= this._nextId) {
      this._nextId = id + 1
    }

    const shellPath = shell || process.env.SHELL || '/bin/zsh'
    const ptyProcess = pty.spawn(shellPath, [], {
      name: 'xterm-256color',
      cols,
      rows,
      cwd: cwd || process.env.HOME || '/',
      env: { ...process.env },
    })

    this._ptys.set(ptyId, ptyProcess)
    return ptyId
  }

  /**
   * Write data to a PTY's stdin.
   * @param {number} id
   * @param {string} data
   */
  writePty(id, data) {
    const p = this._ptys.get(id)
    if (p) p.write(data)
  }

  /**
   * Resize a PTY.
   * @param {number} id
   * @param {number} cols
   * @param {number} rows
   */
  resizePty(id, cols, rows) {
    const p = this._ptys.get(id)
    if (p) p.resize(cols, rows)
  }

  /**
   * Kill a PTY. Sends SIGTERM, then SIGKILL after 2s if still alive.
   * @param {number} id
   * @returns {Promise<void>}
   */
  async killPty(id) {
    const p = this._ptys.get(id)
    if (!p) return

    this._ptys.delete(id)

    try {
      p.kill('SIGTERM')
    } catch {
      // already dead
      return
    }

    // Wait 2s then force-kill if still alive
    await new Promise((resolve) => {
      const timeout = setTimeout(() => {
        try {
          p.kill('SIGKILL')
        } catch {
          // already dead
        }
        resolve()
      }, 2000)

      p.onExit(() => {
        clearTimeout(timeout)
        resolve()
      })
    })
  }

  /**
   * Kill all PTY instances.
   */
  async killAll() {
    const ids = [...this._ptys.keys()]
    await Promise.all(ids.map((id) => this.killPty(id)))
  }

  /**
   * Get a PTY instance by ID.
   * @param {number} id
   * @returns {import('node-pty').IPty|undefined}
   */
  getPty(id) {
    return this._ptys.get(id)
  }

  /**
   * Register a data handler for PTY stdout.
   * @param {number} id
   * @param {(data: string) => void} callback
   * @returns {import('node-pty').IDisposable|undefined}
   */
  onData(id, callback) {
    const p = this._ptys.get(id)
    if (p) return p.onData(callback)
  }
}

/**
 * Register terminal IPC handlers on the main process.
 * @param {import('electron').IpcMain} ipcMain
 * @param {PtyManager} ptyManager
 */
export function setupTerminalIPC(ipcMain, ptyManager) {
  ipcMain.handle('terminal:create', (event, opts = {}) => {
    const id = ptyManager.createPty(null, opts)
    const webContents = event.sender

    // Forward PTY data to the renderer
    ptyManager.onData(id, (data) => {
      if (!webContents.isDestroyed()) {
        webContents.send('terminal:data', { id, data })
      }
    })

    // Notify renderer when PTY exits
    const p = ptyManager.getPty(id)
    if (p) {
      p.onExit(({ exitCode, signal }) => {
        if (!webContents.isDestroyed()) {
          webContents.send('terminal:exit', { id, exitCode, signal })
        }
      })
    }

    return id
  })

  ipcMain.on('terminal:input', (event, { id, data }) => {
    ptyManager.writePty(id, data)
  })

  ipcMain.on('terminal:resize', (event, { id, cols, rows }) => {
    ptyManager.resizePty(id, cols, rows)
  })

  ipcMain.handle('terminal:close', async (event, { id }) => {
    await ptyManager.killPty(id)
  })
}
