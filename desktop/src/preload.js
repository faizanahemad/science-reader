import { contextBridge, ipcRenderer, webUtils } from 'electron'

contextBridge.exposeInMainWorld('__isElectronDesktop', true)

const SEND_CHANNELS = [
  // Original channels
  'window-hide',
  'window-show',
  'window-resize',
  'terminal-input',
  'shell-run',
  // M1.1 Sidebar channels
  'sidebar:tab-changed',
  'sidebar:snap',
  // M2.1 Focus channels
  'focus:activate',
  'focus:escape',
  // M1.2 Chat channels
  'chat:retry-load',
  // M4.1 File drop channels
  'file-drop:open-global-docs',
  // Dock mode channels
  'sidebar:dock-mode',
  // App mode channels
  'sidebar:app-mode',
  'sidebar:window-drag',
  // Notification channels
  'notification:show'
]

const RECEIVE_CHANNELS = [
  // Original channels
  'terminal-output',
  'shell-result',
  'window-state',
  'file-drop',
  // M1.1 Sidebar channels
  'sidebar:snap-changed',
  'sidebar:dock-mode-changed',
  'sidebar:app-mode-changed',
  // M2.1 Focus channels
  'focus:state-changed',
  // M4.2 Bridge channels
  'bridge:open-global-docs',
  'bridge:open-pkb-modal',
  'bridge:open-pkb-ingest',
  'bridge:fill-chat-input',
  'bridge:attach-file',
  // Notification channels
  'notification:clicked'
]

const INVOKE_CHANNELS = [
  'settings:get-opencode-config',
  'settings:set-opencode-config',
  'settings:get-env-vars',
  'settings:set-env-vars',
  'accessibility:is-enabled',
  'accessibility:request-access',
  'screenshot:capture-screen',
  'screenshot:ocr',
  'context:get-quick',
  'context:get-full',
  'pkb-pin',
  'pkb-autocomplete',
  'settings:get-notifications-muted',
  'settings:set-notifications-muted'
]

contextBridge.exposeInMainWorld('electronAPI', {
  send: (channel, data) => {
    if (SEND_CHANNELS.includes(channel)) ipcRenderer.send(channel, data)
  },
  on: (channel, func) => {
    if (RECEIVE_CHANNELS.includes(channel)) {
      ipcRenderer.on(channel, (_e, ...args) => func(...args))
    }
  },
  invoke: (channel, ...args) => {
    if (INVOKE_CHANNELS.includes(channel)) return ipcRenderer.invoke(channel, ...args)
    return Promise.reject(new Error(`Channel "${channel}" not allowed`))
  },
  removeAllListeners: (channel) => {
    ipcRenderer.removeAllListeners(channel)
  },
  getPathForFile: (file) => webUtils.getPathForFile(file)
})
