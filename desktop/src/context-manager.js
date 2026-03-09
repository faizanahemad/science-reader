/**
 * context-manager.js — Unified context aggregator for Science Reader Desktop.
 * M6.3: Collects context from accessibility, screenshots, and user input,
 * formats it into chips for the PopBar and markdown blocks for chat injection.
 *
 * The ContextManager is the single source of truth for "what the user is looking at"
 * across the entire app. It composes data from:
 *   - AccessibilityHandler (active app, window title, selected text, browser URL, etc.)
 *   - ScreenshotHandler (captured images + OCR text)
 *   - Manual context (user-provided text snippets)
 *
 * Usage:
 *   import { ContextManager } from './context-manager.js'
 *   const ctx = new ContextManager(accessibilityHandler, screenshotHandler)
 *   const full = await ctx.gatherFull()          // { raw, chips, markdown, timestamp }
 *   const chips = ctx.toChips(raw)               // [{ label, value, type }]
 *   const md = ctx.toMarkdown(raw)               // "### Context\n\n..."
 */

export class ContextManager {
  constructor (accessibilityHandler, screenshotHandler) {
    this._ax = accessibilityHandler
    this._ss = screenshotHandler
    this._manualContext = []     // user-added context snippets
    this._lastScreenshot = null  // last screenshot result { imagePath, ocrText, width, height }
  }

  // ── Public API ──

  /**
   * Gather full context from all sources.
   * Returns { raw, chips, markdown, timestamp }.
   */
  async gatherFull (opts = {}) {
    const raw = this._gatherRaw(opts)
    return {
      raw,
      chips: this.toChips(raw),
      markdown: this.toMarkdown(raw),
      timestamp: Date.now()
    }
  }

  /**
   * Quick gather — accessibility context only (synchronous, no screenshot).
   * Returns { raw, chips, markdown, timestamp }.
   */
  gatherQuick () {
    const raw = this._gatherRaw({ skipScreenshot: true })
    return {
      raw,
      chips: this.toChips(raw),
      markdown: this.toMarkdown(raw),
      timestamp: Date.now()
    }
  }

  /**
   * Store a screenshot result for inclusion in future context gathers.
   */
  setScreenshot (screenshotResult) {
    if (!screenshotResult) return
    this._lastScreenshot = {
      imagePath: screenshotResult.imagePath || null,
      ocrText: screenshotResult.text || screenshotResult.ocrText || '',
      width: screenshotResult.width || 0,
      height: screenshotResult.height || 0,
      timestamp: Date.now()
    }
  }

  /**
   * Add a manual context snippet.
   */
  addManualContext (label, value) {
    if (!value) return
    // Deduplicate by label
    this._manualContext = this._manualContext.filter(c => c.label !== label)
    this._manualContext.push({ label, value, timestamp: Date.now() })
    // Keep last 10
    if (this._manualContext.length > 10) {
      this._manualContext = this._manualContext.slice(-10)
    }
  }

  /**
   * Remove a manual context snippet by label.
   */
  removeManualContext (label) {
    this._manualContext = this._manualContext.filter(c => c.label !== label)
  }

  /**
   * Clear all transient context (screenshot + manual).
   */
  clearTransient () {
    this._lastScreenshot = null
    this._manualContext = []
  }

  /**
   * Convert raw context into PopBar chips format.
   * Returns [{ label, value, type }].
   */
  toChips (raw) {
    const chips = []

    if (raw.app?.name) {
      chips.push({ label: `📱 ${raw.app.name}`, value: raw.app.name, type: 'app' })
    }

    if (raw.windowTitle) {
      const short = raw.windowTitle.length > 40
        ? raw.windowTitle.slice(0, 37) + '...'
        : raw.windowTitle
      chips.push({ label: `🪟 ${short}`, value: raw.windowTitle, type: 'window' })
    }

    if (raw.selectedText) {
      const short = raw.selectedText.length > 50
        ? raw.selectedText.slice(0, 47) + '...'
        : raw.selectedText
      chips.push({ label: `📋 ${short}`, value: raw.selectedText, type: 'selection' })
    }

    if (raw.browserURL) {
      const short = raw.browserURL.length > 50
        ? raw.browserURL.slice(0, 47) + '...'
        : raw.browserURL
      chips.push({ label: `🌐 ${short}`, value: raw.browserURL, type: 'url' })
    }

    if (raw.finderSelection?.length) {
      const count = raw.finderSelection.length
      chips.push({
        label: `📁 ${count} file${count > 1 ? 's' : ''}`,
        value: raw.finderSelection.join('\n'),
        type: 'files'
      })
    }

    if (raw.vsCodeFile) {
      chips.push({ label: `💻 ${raw.vsCodeFile}`, value: raw.vsCodeFile, type: 'vscode' })
    }

    if (raw.screenshot) {
      const ocrPreview = raw.screenshot.ocrText
        ? raw.screenshot.ocrText.slice(0, 40) + '...'
        : `${raw.screenshot.width}×${raw.screenshot.height}`
      chips.push({ label: `📸 ${ocrPreview}`, value: raw.screenshot.ocrText || raw.screenshot.imagePath, type: 'screenshot' })
    }

    for (const mc of raw.manualContext || []) {
      chips.push({ label: `📌 ${mc.label}`, value: mc.value, type: 'manual' })
    }

    return chips
  }

  /**
   * Convert raw context into a markdown block for chat injection.
   */
  toMarkdown (raw) {
    const parts = []

    if (raw.app?.name) {
      parts.push(`**App:** ${raw.app.name}`)
    }
    if (raw.windowTitle) {
      parts.push(`**Window:** ${raw.windowTitle}`)
    }
    if (raw.browserURL) {
      parts.push(`**URL:** ${raw.browserURL}`)
    }
    if (raw.vsCodeFile) {
      parts.push(`**File:** ${raw.vsCodeFile}`)
    }
    if (raw.finderSelection?.length) {
      parts.push(`**Files:**\n${raw.finderSelection.map(f => `- \`${f}\``).join('\n')}`)
    }
    if (raw.selectedText) {
      const text = raw.selectedText.length > 2000
        ? raw.selectedText.slice(0, 2000) + '\n...(truncated)'
        : raw.selectedText
      parts.push(`**Selected Text:**\n\`\`\`\n${text}\n\`\`\``)
    }
    if (raw.screenshot?.ocrText) {
      const text = raw.screenshot.ocrText.length > 2000
        ? raw.screenshot.ocrText.slice(0, 2000) + '\n...(truncated)'
        : raw.screenshot.ocrText
      parts.push(`**Screenshot OCR:**\n\`\`\`\n${text}\n\`\`\``)
    }
    for (const mc of raw.manualContext || []) {
      parts.push(`**${mc.label}:**\n${mc.value}`)
    }

    if (parts.length === 0) return ''
    return `### Context\n\n${parts.join('\n\n')}`
  }

  // ── Internal ──

  _gatherRaw (opts = {}) {
    // Accessibility context (synchronous)
    const axContext = this._ax?.getContext('text') || {}

    const raw = {
      app: axContext.app || null,
      windowTitle: axContext.windowTitle || null,
      selectedText: axContext.selectedText || null,
      browserURL: axContext.browserURL || null,
      finderSelection: axContext.finderSelection || null,
      vsCodeFile: axContext.vsCodeFile || null,
      screenshot: (!opts.skipScreenshot && this._lastScreenshot) ? this._lastScreenshot : null,
      manualContext: this._manualContext.length > 0 ? [...this._manualContext] : null
    }

    return raw
  }
}
