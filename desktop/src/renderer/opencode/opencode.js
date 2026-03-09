/**
 * opencode.js — Renderer logic for the OpenCode tab.
 *
 * Manages the directory picker dropdown, status display, error banner,
 * and communicates with the main process via the opencodeAPI bridge.
 */

// ── DOM References ──────────────────────────────────────────────────

const $dirBtn = document.getElementById('oc-dir-btn')
const $dirPath = document.getElementById('oc-dir-path')
const $dirDropdown = document.getElementById('oc-dir-dropdown')
const $pinnedSection = document.getElementById('oc-pinned-section')
const $pinnedList = document.getElementById('oc-pinned-list')
const $recentSection = document.getElementById('oc-recent-section')
const $recentList = document.getElementById('oc-recent-list')
const $browseBtn = document.getElementById('oc-browse-btn')

const $statusDot = document.getElementById('oc-status-dot')
const $statusText = document.getElementById('oc-status-text')

const $restartBtn = document.getElementById('oc-restart-btn')
const $stopBtn = document.getElementById('oc-stop-btn')

const $errorBanner = document.getElementById('oc-error-banner')
const $errorMsg = document.getElementById('oc-error-msg')
const $errorRestartBtn = document.getElementById('oc-error-restart-btn')
const $errorDismissBtn = document.getElementById('oc-error-dismiss-btn')

const $placeholder = document.getElementById('oc-placeholder')
const $startBtn = document.getElementById('oc-start-btn')
const $notFoundMsg = document.getElementById('oc-not-found-msg')
const $webviewContainer = document.getElementById('oc-webview-container')

// ── State ───────────────────────────────────────────────────────────

let currentDir = null
let currentStatus = 'disconnected'
let dropdownOpen = false

// ── Helpers ─────────────────────────────────────────────────────────

/**
 * Extract the last component of a path for display.
 * @param {string} fullPath
 * @returns {string}
 */
function dirName (fullPath) {
  const parts = fullPath.replace(/\/$/, '').split(/[/\\]/)
  return parts[parts.length - 1] || fullPath
}

/**
 * Truncate a path for display in the header button.
 * @param {string} fullPath
 * @param {number} maxLen
 * @returns {string}
 */
function truncatePath (fullPath, maxLen = 45) {
  if (fullPath.length <= maxLen) return fullPath
  const name = dirName(fullPath)
  if (name.length >= maxLen - 4) return '…' + name.slice(-(maxLen - 1))
  return '…' + fullPath.slice(-(maxLen - 1))
}

// ── Dropdown ────────────────────────────────────────────────────────

function toggleDropdown () {
  dropdownOpen = !dropdownOpen
  if (dropdownOpen) {
    populateDropdown()
    $dirDropdown.classList.remove('hidden')
  } else {
    $dirDropdown.classList.add('hidden')
  }
}

function closeDropdown () {
  dropdownOpen = false
  $dirDropdown.classList.add('hidden')
}

async function populateDropdown () {
  const [pinned, recent] = await Promise.all([
    window.opencodeAPI.getPinnedDirs(),
    window.opencodeAPI.getRecentDirs()
  ])

  // Pinned section
  if (pinned.length > 0) {
    $pinnedSection.classList.remove('hidden')
    $pinnedList.innerHTML = ''
    for (const dir of pinned) {
      $pinnedList.appendChild(createDirItem(dir, true))
    }
  } else {
    $pinnedSection.classList.add('hidden')
  }

  // Recent section (exclude pinned dirs to avoid duplicates)
  const pinnedSet = new Set(pinned)
  const filteredRecent = recent.filter((d) => !pinnedSet.has(d))
  if (filteredRecent.length > 0) {
    $recentSection.classList.remove('hidden')
    $recentList.innerHTML = ''
    for (const dir of filteredRecent) {
      $recentList.appendChild(createDirItem(dir, false))
    }
  } else {
    $recentSection.classList.add('hidden')
  }
}

/**
 * Create a directory list item element.
 * @param {string} dir
 * @param {boolean} isPinned
 * @returns {HTMLLIElement}
 */
function createDirItem (dir, isPinned) {
  const li = document.createElement('li')
  li.className = 'dir-item'

  const info = document.createElement('div')
  info.className = 'dir-item-info'

  const name = document.createElement('div')
  name.className = 'dir-item-name'
  name.textContent = dirName(dir)

  const path = document.createElement('div')
  path.className = 'dir-item-path'
  path.textContent = dir

  info.appendChild(name)
  info.appendChild(path)

  const pinBtn = document.createElement('button')
  pinBtn.className = 'pin-btn' + (isPinned ? ' pinned' : '')
  pinBtn.textContent = isPinned ? '★' : '☆'
  pinBtn.title = isPinned ? 'Unpin' : 'Pin'
  pinBtn.addEventListener('click', async (e) => {
    e.stopPropagation()
    if (isPinned) {
      await window.opencodeAPI.unpinDir(dir)
    } else {
      await window.opencodeAPI.pinDir(dir)
    }
    populateDropdown()
  })

  li.appendChild(info)
  li.appendChild(pinBtn)

  // Clicking the item selects the directory
  li.addEventListener('click', () => {
    closeDropdown()
    selectDirectory(dir)
  })

  return li
}

// ── Directory Selection ─────────────────────────────────────────────

async function browseDirectory () {
  const dir = await window.opencodeAPI.browseDir()
  if (dir) {
    closeDropdown()
    selectDirectory(dir)
  }
}

async function selectDirectory (dir) {
  currentDir = dir
  $dirPath.textContent = truncatePath(dir)
  $dirPath.title = dir

  // Hide placeholder, show webview container area
  hideError()

  // Start opencode in this directory
  try {
    await window.opencodeAPI.start(dir)
  } catch (err) {
    if (err.message && err.message.includes('not found')) {
      $notFoundMsg.classList.remove('hidden')
    }
    showError(err.message || 'Failed to start OpenCode')
  }
}

// ── Status Management ───────────────────────────────────────────────

function setStatus (status) {
  currentStatus = status

  // Update dot class
  $statusDot.className = 'status-dot ' + status

  // Update text
  const labels = {
    connected: 'Connected',
    disconnected: 'Disconnected',
    starting: 'Starting…',
    error: 'Error'
  }
  $statusText.textContent = labels[status] || status

  // Update restart button state
  $restartBtn.disabled = status === 'starting'
  $stopBtn.disabled = (status === 'disconnected' || status === 'starting')

  // Show/hide placeholder vs webview area
  if (status === 'connected') {
    $placeholder.classList.add('hidden')
    $webviewContainer.classList.remove('hidden')
    $restartBtn.disabled = false
    $stopBtn.disabled = false
  } else if (status === 'disconnected' && !currentDir) {
    $placeholder.classList.remove('hidden')
    $webviewContainer.classList.add('hidden')
  }
}

// ── Error Management ────────────────────────────────────────────────

function showError (message) {
  $errorMsg.textContent = message
  $errorBanner.classList.remove('hidden')
  setStatus('error')
}

function hideError () {
  $errorBanner.classList.add('hidden')
  $notFoundMsg.classList.add('hidden')
}

// ── Restart ─────────────────────────────────────────────────────────

async function restartOpenCode () {
  if (!currentDir) return
  hideError()
  try {
    await window.opencodeAPI.restart(currentDir)
  } catch (err) {
    showError(err.message || 'Failed to restart OpenCode')
  }
}

async function stopOpenCode () {
  if (currentStatus === 'disconnected') return
  hideError()
  try {
    await window.opencodeAPI.stop()
    setStatus('disconnected')
    // Show placeholder again since we explicitly stopped
    $placeholder.classList.remove('hidden')
    $webviewContainer.classList.add('hidden')
  } catch (err) {
    showError(err.message || 'Failed to stop OpenCode')
  }
}

// ── Event Listeners ─────────────────────────────────────────────────

// Directory picker dropdown toggle
$dirBtn.addEventListener('click', () => toggleDropdown())

// Close dropdown when clicking outside
document.addEventListener('click', (e) => {
  if (dropdownOpen && !$dirBtn.contains(e.target) && !$dirDropdown.contains(e.target)) {
    closeDropdown()
  }
})

// Close dropdown on Escape
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && dropdownOpen) {
    closeDropdown()
  }
})

// Browse buttons
$browseBtn.addEventListener('click', () => browseDirectory())
$startBtn.addEventListener('click', () => browseDirectory())

// Restart buttons
$restartBtn.addEventListener('click', () => restartOpenCode())
$errorRestartBtn.addEventListener('click', () => restartOpenCode())
$stopBtn.addEventListener('click', () => stopOpenCode())

// Dismiss error
$errorDismissBtn.addEventListener('click', () => hideError())

// ── IPC Event Handlers ──────────────────────────────────────────────

window.opencodeAPI.onStatus((status) => {
  setStatus(status)
})

window.opencodeAPI.onError((error) => {
  showError(error)
})

window.opencodeAPI.onReady((port) => {
  setStatus('connected')
  console.log(`[OpenCode] Ready on port ${port}`)
  // The main process will mount a WebContentsView pointing to this port.
  // The renderer just needs to ensure the container is visible.
  $placeholder.classList.add('hidden')
  $webviewContainer.classList.remove('hidden')
})

// ── Init ────────────────────────────────────────────────────────────

setStatus('disconnected')
