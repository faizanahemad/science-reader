/**
 * preload-popbar.js — Preload script for the PopBar BrowserWindow.
 * Exposes a scoped electronAPI with whitelisted IPC channels.
 * M3.3: Also exposes markdown renderer (marked + highlight.js) via contextBridge.
 */
import { contextBridge, ipcRenderer, webUtils } from 'electron'
import { createRequire } from 'node:module'

// Load marked + highlight.js via CJS require (Node.js context in preload)
const require_ = createRequire(import.meta.url)
const { marked } = require_('marked')
const hljs = require_('highlight.js/lib/common')

contextBridge.exposeInMainWorld('__isElectronDesktop', true)

const SEND_CHANNELS = [
  'popbar:action',
  'popbar:activate',
  'popbar:escape',
  'popbar:resize',
  'popbar:copy',
  'popbar:replace',
  'popbar:expand',
  'popbar:memory-quick-save',
  'popbar:memory-review',
  'popbar:memory-extract',
  'popbar:run-prompt',
  // M4.1 File drop
  'popbar:file-drop',
  // M7.3: PKB actions
  'popbar:pkb-use-in-chat'
]

const RECEIVE_CHANNELS = [
  'focus:state-changed',
  'popbar:context-update',
  'popbar:stream-chunk',
  'popbar:stream-done',
  'popbar:stream-error',
  'popbar:tool-status',
  'popbar:show-memory-form',
  'popbar:show-search-results',
  'popbar:show-image-result',
  'popbar:memory-save-result',
  'popbar:show-loading',
  'popbar:prefill-input'
]

const INVOKE_CHANNELS = [
  // M6.1: Accessibility
  'accessibility:get-context',
  'accessibility:get-active-app',
  'accessibility:get-selected-text',
  'accessibility:get-window-title',
  'accessibility:get-browser-url',
  'accessibility:get-finder-selection',
  'accessibility:is-enabled',
  'accessibility:request-access',
  // M6.2: Screenshot
  'screenshot:capture-screen',
  'screenshot:capture-window',
  'screenshot:capture-and-ocr',
  'screenshot:list-sources',
  'screenshot:run-ocr',
  // M6.3: Context
  'context:get-full',
  'context:get-quick',
  'context:add-manual',
  'context:remove-manual',
  'context:clear',
  'context:inject-chat',
  // M7.3: PKB pin
  'popbar:pkb-pin',
  // M7.4: PKB autocomplete
  'popbar:pkb-autocomplete'
]

// Configure marked with highlight.js code block rendering
marked.use({
  renderer: {
    code (token) {
      const lang = token.lang || ''
      let highlighted = token.text
      try {
        if (lang && hljs.getLanguage(lang)) {
          highlighted = hljs.highlight(token.text, { language: lang }).value
        } else {
          highlighted = hljs.highlightAuto(token.text).value
        }
      } catch (_) { /* fallback to raw */ }
      return `<pre><code class="hljs language-${lang}">${highlighted}</code></pre>`
    }
  }
})

contextBridge.exposeInMainWorld('electronAPI', {
  send: (channel, data) => {
    if (SEND_CHANNELS.includes(channel)) ipcRenderer.send(channel, data)
  },
  invoke: (channel, data) => {
    if (INVOKE_CHANNELS.includes(channel)) return ipcRenderer.invoke(channel, data)
    return Promise.reject(new Error(`Channel not allowed: ${channel}`))
  },
  on: (channel, func) => {
    if (RECEIVE_CHANNELS.includes(channel)) {
      ipcRenderer.on(channel, (_e, ...args) => func(...args))
    }
  },
  removeAllListeners: (channel) => {
    ipcRenderer.removeAllListeners(channel)
  },
  renderMarkdown: (text) => marked.parse(text),
  getPathForFile: (file) => webUtils.getPathForFile(file)
})
