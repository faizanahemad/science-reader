/**
 * opencode-manager.js — Manages the `opencode web` child process lifecycle.
 *
 * Handles spawning/stopping the opencode web server, generating MCP config
 * (opencode.json), and persisting recent/pinned working directories.
 *
 * Usage:
 *   import { OpenCodeManager, setupOpenCodeIPC } from './opencode-manager.js'
 *   const manager = new OpenCodeManager()
 *   await manager.start('/path/to/project', jwtToken, 9123)
 */
import { spawn } from 'node:child_process'
import { writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { createServer } from 'node:net'
import { fileURLToPath } from 'node:url'
import Store from 'electron-store'

const __dirname = join(fileURLToPath(import.meta.url), '..')
const OPENCODE_PICKER_HTML = join(__dirname, 'renderer', 'opencode', 'opencode.html')

// ── Helpers ─────────────────────────────────────────────────────────────

/**
 * Find a free TCP port starting from `preferred`, incrementing on conflict.
 * @param {number} preferred
 * @returns {Promise<number>}
 */
function findFreePort (preferred = 4200) {
  return new Promise((resolve, reject) => {
    const srv = createServer()
    srv.unref()
    srv.on('error', (err) => {
      if (err.code === 'EADDRINUSE' && preferred < 4300) {
        resolve(findFreePort(preferred + 1))
      } else {
        reject(err)
      }
    })
    srv.listen(preferred, '127.0.0.1', () => {
      const { port } = srv.address()
      srv.close(() => resolve(port))
    })
  })
}

// ── OpenCodeManager ─────────────────────────────────────────────────────

export class OpenCodeManager {
  /** @type {import('node:child_process').ChildProcess | null} */
  process = null
  /** @type {number | null} */
  port = null
  /** @type {string | null} */
  cwd = null
  /** @type {Store} */
  store

  constructor () {
    this.store = new Store({
      name: 'opencode-manager',
      defaults: {
        recentDirs: [],
        pinnedDirs: []
      }
    })
  }

  /** Set custom environment variables to pass to OpenCode process. */
  setCustomEnvVars (vars) { this._customEnvVars = vars || {} }

  /** Set custom opencode.json content (empty string = use default). */
  setCustomConfig (configJson) { this._customConfigJson = configJson || '' }

  // ── Process Lifecycle ───────────────────────────────────────────────
  /**
   * Start `opencode web` as a child process.
   *
   * @param {string} cwd - Working directory for the opencode session
   * @param {string} mcpJwtToken - JWT for remote MCP server auth
   * @param {number} mcpFsPort - Local filesystem MCP server port
   * @returns {Promise<{ port: number, process: import('node:child_process').ChildProcess }>}
   */
  async start (cwd, mcpJwtToken, mcpFsPort) {
    if (this.process) {
      throw new Error('OpenCode is already running. Call stop() first.')
    }

    this.cwd = cwd

    // Generate opencode.json config in the working directory
    await this.generateConfig(cwd, mcpJwtToken, mcpFsPort)

    // Find a free port for the opencode web server
    const port = await findFreePort(4200)
    this.port = port

    // Build environment — forward current env plus the JWT token + custom env vars
    const customEnvVars = this._customEnvVars || {}
    const env = { ...process.env, MCP_JWT_TOKEN: mcpJwtToken, BROWSER: 'none', ...customEnvVars }
    // Spawn opencode web
    const child = spawn('opencode', ['web', '--port', String(port), '--hostname', '127.0.0.1'], {
      cwd,
      env,
      stdio: ['ignore', 'pipe', 'pipe']
    })

    this.process = child

    // Capture stdout/stderr for debugging
    this._stdout = ''
    this._stderr = ''

    child.stdout.on('data', (chunk) => {
      this._stdout += chunk.toString()
    })

    child.stderr.on('data', (chunk) => {
      this._stderr += chunk.toString()
    })

    // Track unexpected exits
    child.on('error', (err) => {
      this._lastError = err
      this.process = null
      this.port = null
    })

    child.on('exit', (code, signal) => {
      this._exitCode = code
      this._exitSignal = signal
      this.process = null
      this.port = null
    })

    // Wait for the server to become ready (look for "listening" or port in output)
    await this._waitForReady(child, port)

    // Persist this directory as recent
    this.addRecentDir(cwd)

    return { port, process: child }
  }

  /**
   * Wait for the opencode web server to signal readiness.
   * Resolves when stdout/stderr contains "listening" or the port number,
   * or after a 15-second timeout.
   *
   * @param {import('node:child_process').ChildProcess} child
   * @param {number} port
   * @returns {Promise<void>}
   */
  _waitForReady (child, port) {
    return new Promise((resolve, reject) => {
      const timeout = setTimeout(() => {
        cleanup()
        // Resolve anyway after timeout — server may be ready without logging
        resolve()
      }, 15_000)

      const check = (data) => {
        const text = data.toString().toLowerCase()
        if (text.includes('listening') || text.includes(String(port)) || text.includes('ready') || text.includes('started')) {
          cleanup()
          resolve()
        }
      }

      const onError = (err) => {
        cleanup()
        reject(new Error(`OpenCode process failed to start: ${err.message}`))
      }

      const onExit = (code) => {
        cleanup()
        if (code !== 0 && code !== null) {
          const stderr = this._stderr || '(no output)'
          reject(new Error(`OpenCode exited with code ${code}: ${stderr}`))
        }
      }

      const cleanup = () => {
        clearTimeout(timeout)
        child.stdout?.removeListener('data', check)
        child.stderr?.removeListener('data', check)
        child.removeListener('error', onError)
        child.removeListener('exit', onExit)
      }

      child.stdout?.on('data', check)
      child.stderr?.on('data', check)
      child.once('error', onError)
      child.once('exit', onExit)
    })
  }

  /**
   * Stop the running opencode web process gracefully.
   * Sends SIGTERM, waits up to 3 seconds, then SIGKILL if still alive.
   * @returns {Promise<void>}
   */
  async stop () {
    const child = this.process
    if (!child) return

    return new Promise((resolve) => {
      const forceKillTimer = setTimeout(() => {
        try { child.kill('SIGKILL') } catch { /* already dead */ }
      }, 3000)

      child.once('exit', () => {
        clearTimeout(forceKillTimer)
        this.process = null
        this.port = null
        this.cwd = null
        this._stdout = ''
        this._stderr = ''
        resolve()
      })

      try {
        child.kill('SIGTERM')
      } catch {
        // Process already dead
        clearTimeout(forceKillTimer)
        this.process = null
        this.port = null
        this.cwd = null
        resolve()
      }
    })
  }

  /**
   * Restart opencode with a (potentially new) working directory.
   *
   * @param {string} newCwd
   * @param {string} mcpJwtToken
   * @param {number} mcpFsPort
   * @returns {Promise<{ port: number, process: import('node:child_process').ChildProcess }>}
   */
  async restart (newCwd, mcpJwtToken, mcpFsPort) {
    await this.stop()
    return this.start(newCwd, mcpJwtToken, mcpFsPort)
  }

  // ── Config Generation ───────────────────────────────────────────────

  /**
   * Generate `opencode.json` in the given working directory with
   * MCP server configuration for all remote + local servers.
   *
   * @param {string} cwd
   * @param {string} mcpJwtToken
   * @param {number} mcpFsPort
   */
  async generateConfig (cwd, mcpJwtToken, mcpFsPort) {
    // If user has a custom config, use it directly
    if (this._customConfigJson) {
      await writeFile(join(cwd, 'opencode.json'), this._customConfigJson)
      return
    }

    // Otherwise generate default config
    const configStr = this._buildDefaultConfig(mcpJwtToken, mcpFsPort)
    await writeFile(join(cwd, 'opencode.json'), configStr)
  }

  /**
   * Get the default opencode.json as a formatted JSON string.
   * Used by the settings panel to show the default config.
   */
  getDefaultConfig () {
    return this._buildDefaultConfig('<JWT_TOKEN>', 0)
  }

  /** Build the default config JSON string. */
  _buildDefaultConfig (mcpJwtToken, mcpFsPort) {
    const authHeaders = { Authorization: `Bearer ${mcpJwtToken}` }
    const baseUrl = 'https://assist-chat.site/mcp'

    const config = {
      $schema: 'https://opencode.ai/config.json',
      model: 'anthropic/claude-sonnet-4.6',
      small_model: 'anthropic/claude-haiku-4-5',
      permission: {
        bash: 'allow',
        edit: 'allow',
        webfetch: 'allow'
      },
      compaction: {
        auto: true,
        prune: true,
        reserved: 10000
      },
      provider: {
        openrouter: {
          models: {},
          options: {
            apiKey: '{env:OPENROUTER_API_KEY}'
          }
        },
        'amazon-bedrock': {
          models: {},
          options: {
            region: 'us-east-1',
            apiKey: '{env:BEDROCK_API_KEY}'
          }
        }
      },
      mcp: {
        search: {
          type: 'remote',
          url: `${baseUrl}/search/mcp`,
          oauth: false,
          headers: authHeaders,
          enabled: true
        },
        pkb: {
          type: 'remote',
          url: `${baseUrl}/pkb/mcp`,
          oauth: false,
          headers: authHeaders,
          enabled: true
        },
        docs: {
          type: 'remote',
          url: `${baseUrl}/docs/mcp`,
          oauth: false,
          headers: authHeaders,
          enabled: true
        },
        artefacts: {
          type: 'remote',
          url: `${baseUrl}/artefacts/mcp`,
          oauth: false,
          headers: authHeaders,
          enabled: true
        },
        conversations: {
          type: 'remote',
          url: `${baseUrl}/conversations/mcp`,
          oauth: false,
          headers: authHeaders,
          enabled: true
        },
        prompts: {
          type: 'remote',
          url: `${baseUrl}/prompts/mcp`,
          oauth: false,
          headers: authHeaders,
          enabled: true
        },
        code: {
          type: 'remote',
          url: `${baseUrl}/code/mcp`,
          oauth: false,
          headers: authHeaders,
          enabled: true
        },
        image: {
          type: 'remote',
          url: `${baseUrl}/image/mcp`,
          oauth: false,
          headers: authHeaders,
          enabled: true
        },
        filesystem: {
          type: 'remote',
          url: `http://127.0.0.1:${mcpFsPort}/mcp`,
          oauth: false,
          enabled: true
        }
      },
      server: {
        port: 4096,
        hostname: '127.0.0.1'
      }
    }

    return JSON.stringify(config, null, 2)
  }

  // ── Directory Management ────────────────────────────────────────────

  /**
   * Get the list of recent working directories (last 10).
   * @returns {string[]}
   */
  getRecentDirs () {
    return this.store.get('recentDirs', [])
  }

  /**
   * Add a directory to the recent list.
   * Deduplicates and caps at 10 entries.
   * @param {string} dir
   */
  addRecentDir (dir) {
    let recent = this.store.get('recentDirs', [])
    recent = recent.filter((d) => d !== dir)
    recent.unshift(dir)
    if (recent.length > 10) recent = recent.slice(0, 10)
    this.store.set('recentDirs', recent)
  }

  /**
   * Get the list of pinned (favorite) directories.
   * @returns {string[]}
   */
  getPinnedDirs () {
    return this.store.get('pinnedDirs', [])
  }

  /**
   * Pin a directory to favorites.
   * @param {string} dir
   */
  pinDir (dir) {
    const pinned = this.store.get('pinnedDirs', [])
    if (!pinned.includes(dir)) {
      pinned.push(dir)
      this.store.set('pinnedDirs', pinned)
    }
  }

  /**
   * Unpin a directory from favorites.
   * @param {string} dir
   */
  unpinDir (dir) {
    const pinned = this.store.get('pinnedDirs', []).filter((d) => d !== dir)
    this.store.set('pinnedDirs', pinned)
  }

  /**
   * Get captured stdout from the child process (for debugging).
   * @returns {string}
   */
  getStdout () {
    return this._stdout || ''
  }

  /**
   * Get captured stderr from the child process (for debugging).
   * @returns {string}
   */
  getStderr () {
    return this._stderr || ''
  }
}

// ── IPC Handler Setup ─────────────────────────────────────────────────

/**
 * Register all OpenCode-related IPC handlers.
 *
 * @param {import('electron').IpcMain} ipcMain
 * @param {OpenCodeManager} openCodeManager
 * @param {import('electron').BrowserWindow} sidebarWindow
 * @param {{ getOpenCodeView: () => import('electron').WebContentsView | null }} options
 */
export function setupOpenCodeIPC (ipcMain, openCodeManager, sidebarWindow, options = {}) {
  const { getOpenCodeView } = options
  // ── Directory management ──
  ipcMain.handle('opencode:get-recent-dirs', () => openCodeManager.getRecentDirs())
  ipcMain.handle('opencode:get-pinned-dirs', () => openCodeManager.getPinnedDirs())
  ipcMain.handle('opencode:pin-dir', (_e, dir) => openCodeManager.pinDir(dir))
  ipcMain.handle('opencode:unpin-dir', (_e, dir) => openCodeManager.unpinDir(dir))

  ipcMain.handle('opencode:browse-dir', async () => {
    const { dialog } = await import('electron')
    const result = await dialog.showOpenDialog(sidebarWindow, {
      properties: ['openDirectory']
    })
    return result.canceled ? null : result.filePaths[0]
  })

  // ── Process management ──

  ipcMain.handle('opencode:start', async (_e, cwd) => {
    try {
      // Notify renderer: starting
      if (sidebarWindow && !sidebarWindow.isDestroyed()) {
        sidebarWindow.webContents.send('opencode:status', 'starting')
      }

      // Read JWT from store or environment
      const store = new Store({ name: 'opencode-manager' })
      const mcpJwtToken = store.get('mcpJwtToken') || process.env.MCP_JWT_TOKEN || ''
      // mcpFsPort would come from the filesystem server; default to 0 if not set
      const mcpFsPort = store.get('mcpFsPort') || 0

      // Inject custom config + env vars from settings store
      const settingsStore = new Store({ name: 'sidebar-settings' })
      const customConfig = settingsStore.get('opencodeCustomConfig', '')
      const customEnvVars = settingsStore.get('opencodeEnvVars', {})
      openCodeManager.setCustomConfig(customConfig)
      openCodeManager.setCustomEnvVars(customEnvVars)

      const { port } = await openCodeManager.start(cwd, mcpJwtToken, mcpFsPort)

      // Notify renderer: ready
      if (sidebarWindow && !sidebarWindow.isDestroyed()) {
        sidebarWindow.webContents.send('opencode:status', 'connected')
        sidebarWindow.webContents.send('opencode:ready', { port })
      }

      // Navigate opencodeView to the OpenCode web UI
      const view = getOpenCodeView?.()
      if (view && !view.webContents.isDestroyed()) {
        view.webContents.loadURL(`http://127.0.0.1:${port}`)
      }

      // Watch for unexpected exit
      openCodeManager.process?.on('exit', (code, signal) => {
        if (sidebarWindow && !sidebarWindow.isDestroyed()) {
          sidebarWindow.webContents.send('opencode:status', 'disconnected')
          if (code !== 0 && code !== null) {
            sidebarWindow.webContents.send('opencode:error',
              `OpenCode exited with code ${code}${signal ? ` (signal: ${signal})` : ''}`)
          }
        }
        // Navigate back to directory picker on unexpected exit
        const view = getOpenCodeView?.()
        if (view && !view.webContents.isDestroyed()) {
          view.webContents.loadFile(OPENCODE_PICKER_HTML)
        }
      })

      return { port }
    } catch (err) {
      if (sidebarWindow && !sidebarWindow.isDestroyed()) {
        sidebarWindow.webContents.send('opencode:status', 'error')
        sidebarWindow.webContents.send('opencode:error', err.message)
      }
      throw err
    }
  })

  ipcMain.handle('opencode:stop', async () => {
    await openCodeManager.stop()
    if (sidebarWindow && !sidebarWindow.isDestroyed()) {
      sidebarWindow.webContents.send('opencode:status', 'disconnected')
    }
    // Navigate back to directory picker
    const view = getOpenCodeView?.()
    if (view && !view.webContents.isDestroyed()) {
      view.webContents.loadFile(OPENCODE_PICKER_HTML)
    }
  })

  ipcMain.handle('opencode:restart', async (_e, cwd) => {
    try {
      if (sidebarWindow && !sidebarWindow.isDestroyed()) {
        sidebarWindow.webContents.send('opencode:status', 'starting')
      }

      const store = new Store({ name: 'opencode-manager' })
      const mcpJwtToken = store.get('mcpJwtToken') || process.env.MCP_JWT_TOKEN || ''
      const mcpFsPort = store.get('mcpFsPort') || 0

      const { port } = await openCodeManager.restart(cwd, mcpJwtToken, mcpFsPort)

      if (sidebarWindow && !sidebarWindow.isDestroyed()) {
        sidebarWindow.webContents.send('opencode:status', 'connected')
        sidebarWindow.webContents.send('opencode:ready', { port })
      }

      // Navigate opencodeView to the OpenCode web UI
      const view = getOpenCodeView?.()
      if (view && !view.webContents.isDestroyed()) {
        view.webContents.loadURL(`http://127.0.0.1:${port}`)
      }

      openCodeManager.process?.on('exit', (code, signal) => {
        if (sidebarWindow && !sidebarWindow.isDestroyed()) {
          sidebarWindow.webContents.send('opencode:status', 'disconnected')
          if (code !== 0 && code !== null) {
            sidebarWindow.webContents.send('opencode:error',
              `OpenCode exited with code ${code}${signal ? ` (signal: ${signal})` : ''}`)
          }
        }
        // Navigate back to directory picker on unexpected exit
        const view = getOpenCodeView?.()
        if (view && !view.webContents.isDestroyed()) {
          view.webContents.loadFile(OPENCODE_PICKER_HTML)
        }
      })

      return { port }
    } catch (err) {
      if (sidebarWindow && !sidebarWindow.isDestroyed()) {
        sidebarWindow.webContents.send('opencode:status', 'error')
        sidebarWindow.webContents.send('opencode:error', err.message)
      }
      throw err
    }
  })
}
