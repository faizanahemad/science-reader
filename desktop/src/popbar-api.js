/**
 * popbar-api.js — PopBar HTTP client for Flask backend.
 * M3.4: Handles Quick Ask (with tool calling), direct LLM actions, and expand-to-conversation.
 */
import { getSessionCookie } from './auth.js'

const SERVER_URL = 'https://assist-chat.site'

// ── Helper: DRY HTTP request wrapper ──

/**
 * Make an authenticated HTTP request to the backend.
 * @param {string} path - URL path (e.g. '/send_message/abc123')
 * @param {object} options
 * @param {string} [options.method='POST']
 * @param {object} [options.body] - JSON-serializable body
 * @param {AbortSignal} [options.signal]
 * @param {Record<string,string>} [options.extraHeaders]
 * @returns {Promise<Response>}
 */
async function makeRequest (path, options = {}) {
  const cookie = await getSessionCookie()
  if (!cookie) throw new Error('Not authenticated — no session cookie')

  const { method = 'POST', body, signal, extraHeaders } = options
  const headers = {
    'Content-Type': 'application/json',
    Cookie: cookie,
    ...extraHeaders
  }

  const fetchOpts = { method, headers, signal }
  if (body !== undefined) fetchOpts.body = JSON.stringify(body)

  const response = await fetch(`${SERVER_URL}${path}`, fetchOpts)
  if (!response.ok) {
    const text = await response.text().catch(() => '')
    throw new Error(`HTTP ${response.status} on ${method} ${path}: ${text.substring(0, 200)}`)
  }
  return response
}

// ── Stream parser helper ──

/**
 * Read a newline-delimited JSON stream and dispatch parsed lines.
 * @param {Response} response
 * @param {function} onLine - Called with each parsed JSON object
 * @param {AbortSignal} [signal]
 */
async function readStreamLines (response, onLine, signal) {
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  try {
    while (true) {
      if (signal?.aborted) break
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      let newlineIdx
      while ((newlineIdx = buffer.indexOf('\n')) !== -1) {
        const line = buffer.slice(0, newlineIdx).trim()
        buffer = buffer.slice(newlineIdx + 1)
        if (line) {
          try {
            onLine(JSON.parse(line))
          } catch (_e) { /* skip unparseable lines */ }
        }
      }
    }
    // Flush remaining buffer
    const remaining = buffer.trim()
    if (remaining) {
      try { onLine(JSON.parse(remaining)) } catch (_e) { /* ignore */ }
    }
  } finally {
    reader.releaseLock()
  }
}

// ── Quick Ask (with optional tool calling) ──

/**
 * Quick Ask: creates a temp conversation, sends a message with streaming, then cleans up.
 * @param {object} params
 * @param {string} params.text - User query
 * @param {string} [params.context] - Optional surrounding context
 * @param {string[]} [params.tools] - Tool whitelist
 * @param {number} [params.maxToolIterations] - Max tool call rounds
 * @param {function} params.onChunk - Called with each text token
 * @param {function} [params.onToolStatus] - Called with (toolName, status)
 * @param {function} params.onDone - Called when streaming completes
 * @param {function} params.onError - Called with error message string
 * @param {AbortSignal} [params.signal] - For cancellation
 */
export async function quickAsk ({ text, context, tools, maxToolIterations, onChunk, onToolStatus, onDone, onError, signal }) {
  let conversationId = null

  try {
    // 1. Create temp conversation
    const createResp = await makeRequest('/create_temporary_conversation/default', {
      body: {},
      signal
    })
    const createData = await createResp.json()
    conversationId = createData.conversation?.conversation_id
    if (!conversationId) throw new Error('No conversation_id in create response')

    // 2. Build message with context
    const message = context ? `Context:\n${context}\n\nQuestion: ${text}` : text

    // 3. Send message and stream response
    const sendResp = await makeRequest(`/send_message/${conversationId}`, {
      body: {
        message,
        checkboxes: {
          persist_or_not: false,
          provide_detailed_answers: 2,
          use_pkb: true,
          enable_previous_messages: '0',
          perform_web_search: false,
          googleScholar: false,
          ppt_answer: false,
          preamble_options: [],
          enabled_tools: tools || ['pkb_search', 'pkb_add_claim']
        },
        search: [],
        links: [],
        source: 'desktop_popbar'
      },
      signal
    })

    await readStreamLines(sendResp, (parsed) => {
      // Text tokens
      if (parsed.text) onChunk(parsed.text)

      // Tool status events
      if (parsed.type === 'tool_call' || parsed.type === 'tool_status') {
        onToolStatus?.(parsed.tool_name || parsed.name, parsed.status || 'running')
      }
      if (parsed.type === 'tool_result') {
        onToolStatus?.(parsed.tool_name || parsed.name, 'done')
      }
    }, signal)

    onDone()
  } catch (err) {
    if (err.name === 'AbortError') {
      onDone() // Treat abort as graceful end
    } else {
      onError(err.message || 'Quick Ask failed')
    }
  } finally {
    // 3. Clean up: delete temp conversation (fire and forget)
    if (conversationId) {
      makeRequest(`/delete_conversation/${conversationId}`, { method: 'DELETE' }).catch(() => {})
    }
  }
}

// ── Direct LLM Action (explain / summarize — no tools) ──

/**
 * Direct LLM action for simple explain/summarize without tool calling.
 * @param {object} params
 * @param {string} params.actionType - "explain", "summarize", or custom
 * @param {string} params.text - Selected text to act on
 * @param {string} [params.context] - Optional surrounding context
 * @param {function} params.onChunk - Called with each text token
 * @param {function} params.onDone - Called when streaming completes
 * @param {function} params.onError - Called with error message string
 * @param {AbortSignal} [params.signal] - For cancellation
 */
export async function directLlmAction ({ actionType, text, context, onChunk, onDone, onError, signal }) {
  try {
    const response = await makeRequest('/temporary_llm_action', {
      body: {
        action_type: actionType,
        selected_text: text,
        user_message: context || '',
        history: [],
        with_context: false
      },
      signal
    })

    let errorSent = false
    await readStreamLines(response, (parsed) => {
      if (parsed.error) {
        onError(parsed.status || `${actionType} action failed`)
        errorSent = true
        return
      }
      if (parsed.text) onChunk(parsed.text)
    }, signal)

    if (!errorSent) onDone()
  } catch (err) {
    if (err.name === 'AbortError') {
      onDone()
    } else {
      onError(err.message || `${actionType} action failed`)
    }
  }
}

// ── Expand to Conversation ──

/**
 * Expand a PopBar result into a full conversation.
 * @param {object} params
 * @param {'new'|'active'} params.mode - Create new or use active conversation
 * @param {string} [params.query] - Original query
 * @param {string} [params.response] - AI response to seed
 * @returns {Promise<{ conversationId: string|null }>}
 */
export async function expandToConversation ({ mode, query, response }) {
  if (mode === 'new') {
    try {
      const createResp = await makeRequest('/create_temporary_conversation/default', {
        body: {}
      })
      const createData = await createResp.json()
      const conversationId = createData.conversation?.conversation_id
      if (!conversationId) throw new Error('No conversation_id in create response')
      return { conversationId }
    } catch (err) {
      console.error('[PopBar API] Failed to create conversation for expand:', err.message)
      return { conversationId: null }
    }
  }

  if (mode === 'active') {
    // TODO: Need to get current active conversation ID from sidebar
    console.log('[PopBar API] Expand to active conversation — not yet implemented')
    return { conversationId: null }
  }

  return { conversationId: null }
}

// ── Save to Memory (Quick Review) ──

/**
 * Quick Save — analyze text then create a PKB claim.
 * @param {object} params
 * @param {string} params.text - Text to save as a memory claim
 * @param {AbortSignal} [params.signal]
 * @returns {Promise<{ success: boolean, claimId?: string, claimNumber?: number, error?: string }>}
 */
export async function saveToMemoryQuick ({ text, signal }) {
  try {
    // 1. Analyze the statement
    const analyzeResp = await makeRequest('/pkb/analyze_statement', {
      body: { text },
      signal
    })
    const analyzed = await analyzeResp.json()

    // 2. Create the claim
    const claimResp = await makeRequest('/pkb/claims', {
      body: {
        statement: text,
        claim_type: analyzed.claim_type,
        context_domain: analyzed.context_domain,
        tags: analyzed.tags,
        auto_extract: false
      },
      signal
    })
    const claim = await claimResp.json()

    return { success: true, claimId: claim.id, claimNumber: claim.claim_number }
  } catch (err) {
    return { success: false, error: err.message || 'Failed to save memory' }
  }
}

// ── Search Memory (PKB) ──

/**
 * Search PKB for matching claims.
 * @param {object} params
 * @param {string} params.query - Search query
 * @param {object} [params.filters] - Optional filters (claim_type, context_domain, etc.)
 * @param {AbortSignal} [params.signal]
 * @returns {Promise<Array>} Array of search result objects
 */
export async function searchMemory ({ query, filters, signal }) {
  const resp = await makeRequest('/pkb/search', {
    body: { query, limit: 10, filters: filters || {} },
    signal
  })
  const data = await resp.json()
  return data.results || []
}

/**
 * Pin or unpin a PKB claim.
 * @param {object} params
 * @param {string} params.claimId - Claim ID to pin/unpin
 * @param {boolean} [params.pin=true] - True to pin, false to unpin
 * @param {AbortSignal} [params.signal]
 * @returns {Promise<object>}
 */
export async function pinClaim ({ claimId, pin = true, signal }) {
  const resp = await makeRequest(`/pkb/pin/${claimId}`, {
    body: { pin },
    signal
  })
  return resp.json()
}

/**
 * Autocomplete PKB references by prefix.
 * @param {object} params
 * @param {string} params.query - Prefix string (characters after @)
 * @param {AbortSignal} [params.signal]
 * @returns {Promise<{ memories: Array, contexts: Array, entities: Array, tags: Array, domains: Array }>}
 */
export async function autocompleteMemory ({ query, signal }) {
  const q = encodeURIComponent(query)
  const resp = await makeRequest(`/pkb/autocomplete?q=${q}&limit=10`, {
    method: 'GET',
    signal
  })
  return resp.json()
}

// ── Generate Image ──

/**
 * Generate an image from a prompt.
 * @param {object} params
 * @param {string} params.prompt - Image generation prompt
 * @param {string} [params.context] - Optional context
 * @param {AbortSignal} [params.signal]
 * @returns {Promise<object>} Parsed JSON with image data or URL
 */
export async function generateImage ({ prompt, context, signal }) {
  const resp = await makeRequest('/api/generate-image', {
    body: { prompt, conversation_id: null },
    signal
  })
  return resp.json()
}

// ── Fetch Prompts ──

/**
 * Get available prompt slots.
 * @param {object} [params]
 * @param {AbortSignal} [params.signal]
 * @returns {Promise<Array>} Array of prompt objects
 */
export async function fetchPrompts ({ signal } = {}) {
  const resp = await makeRequest('/prompts/list', {
    method: 'GET',
    signal
  })
  return resp.json()
}
