/**
 * auth.js — Session cookie extraction and pre-login guard.
 * M1.3: Shares the session cookie with other modules (PopBar, folder sync, etc.)
 */
import { session } from 'electron'

const SERVER_URL = 'https://assist-chat.site'

/** @type {boolean} */
let isAuthenticated = false

/**
 * Get the session cookie from the default Electron session.
 * @returns {Promise<string|null>} Cookie string like "session=value" or null.
 */
export async function getSessionCookie () {
  const cookies = await session.defaultSession.cookies.get({ url: SERVER_URL })
  const sessionCookie = cookies.find(c => c.name === 'session_id' || c.name === 'session')
  return sessionCookie ? `${sessionCookie.name}=${sessionCookie.value}` : null
}

/**
 * Check if user is authenticated. If not, show sidebar and switch to chat tab
 * so the user can log in.
 * @param {import('electron').BrowserWindow} sidebarWindow
 * @param {import('electron').WebContentsView} chatView
 * @returns {Promise<boolean>} true if authenticated, false otherwise.
 */
export async function requireAuth (sidebarWindow, chatView) {
  const cookie = await getSessionCookie()
  if (!cookie) {
    // Show sidebar and ensure chat tab (with login page) is visible
    sidebarWindow.show()
    chatView.setVisible(true)
    isAuthenticated = false
    return false
  }
  isAuthenticated = true
  return true
}

/**
 * Watch chatView navigation for login/logout transitions.
 * @param {import('electron').WebContentsView} chatView
 */
export function watchAuthState (chatView) {
  chatView.webContents.on('did-navigate', async (_event, url) => {
    if (url.includes('/login') || url.includes('/signin')) {
      // Navigated TO login → session expired or not logged in
      isAuthenticated = false
      console.log('[Auth] Session expired or user not logged in')
    } else {
      // Navigated AWAY from login → check for cookie
      const cookie = await getSessionCookie()
      if (cookie) {
        isAuthenticated = true
        console.log('[Auth] Session cookie obtained')
      }
    }
  })

  chatView.webContents.on('did-navigate-in-page', async (_event, url) => {
    if (!url.includes('/login') && !url.includes('/signin')) {
      const cookie = await getSessionCookie()
      if (cookie) {
        isAuthenticated = true
        console.log('[Auth] Session cookie obtained (in-page navigation)')
      }
    }
  })
}

/**
 * Check current auth state (cached).
 * @returns {boolean}
 */
export function isUserAuthenticated () {
  return isAuthenticated
}
