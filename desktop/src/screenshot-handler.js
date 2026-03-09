/**
 * screenshot-handler.js — Screenshot capture + OCR for Science Reader Desktop.
 * M6.2: Uses Electron desktopCapturer for screen/window capture and tesseract.js for OCR.
 *
 * All methods are async and return null on failure (graceful degradation).
 *
 * Usage:
 *   import { ScreenshotHandler } from './screenshot-handler.js'
 *   const sh = new ScreenshotHandler()
 *   const result = await sh.captureScreen()        // { imagePath, dataURL, width, height }
 *   const ocrResult = await sh.captureAndOCR()     // { imagePath, text, confidence }
 *   const sources = await sh.listSources()         // [{ id, name, thumbnailDataURL }]
 */

import { desktopCapturer, screen } from 'electron'
import { writeFile, mkdir } from 'node:fs/promises'
import { join } from 'node:path'
import { tmpdir } from 'node:os'
import { createRequire } from 'node:module'

const require_ = createRequire(import.meta.url)

let Tesseract = null

function loadTesseract () {
  if (Tesseract) return Tesseract
  try {
    Tesseract = require_('tesseract.js')
    return Tesseract
  } catch (err) {
    console.warn('[Screenshot] tesseract.js not available — OCR disabled:', err.message)
    return null
  }
}

export class ScreenshotHandler {
  constructor (opts = {}) {
    this._screenshotDir = opts.screenshotDir || join(tmpdir(), 'science-reader-screenshots')
    this._ocrWorker = null
    this._ocrReady = false
  }

  // ── Public API ──

  /**
   * List available screen and window sources for capture.
   * Returns array of { id, name, thumbnailDataURL, display_id }.
   */
  async listSources (opts = {}) {
    try {
      const types = opts.types || ['screen', 'window']
      const sources = await desktopCapturer.getSources({
        types,
        thumbnailSize: { width: 300, height: 200 },
        fetchWindowIcons: false
      })
      return sources.map(s => ({
        id: s.id,
        name: s.name,
        thumbnailDataURL: s.thumbnail.toDataURL(),
        display_id: s.display_id || null
      }))
    } catch (err) {
      console.error('[Screenshot] listSources failed:', err.message)
      return []
    }
  }

  /**
   * Capture the entire primary screen.
   * Returns { imagePath, dataURL, width, height } or null on failure.
   */
  async captureScreen () {
    try {
      const primaryDisplay = screen.getPrimaryDisplay()
      const { width, height } = primaryDisplay.size
      const scaleFactor = primaryDisplay.scaleFactor || 1

      const sources = await desktopCapturer.getSources({
        types: ['screen'],
        thumbnailSize: { width: Math.round(width * scaleFactor), height: Math.round(height * scaleFactor) }
      })

      if (!sources.length) {
        console.warn('[Screenshot] No screen sources found')
        return null
      }

      // Pick primary display source
      const source = sources.find(s => s.display_id === String(primaryDisplay.id)) || sources[0]
      const image = source.thumbnail

      if (image.isEmpty()) {
        console.warn('[Screenshot] Captured empty image')
        return null
      }

      const imagePath = await this._saveImage(image, 'screen')
      return {
        imagePath,
        dataURL: image.toDataURL(),
        width: image.getSize().width,
        height: image.getSize().height
      }
    } catch (err) {
      console.error('[Screenshot] captureScreen failed:', err.message)
      return null
    }
  }

  /**
   * Capture a specific window by source ID (from listSources).
   * Returns { imagePath, dataURL, width, height } or null on failure.
   */
  async captureWindow (sourceId) {
    try {
      if (!sourceId) {
        console.warn('[Screenshot] No sourceId provided')
        return null
      }

      const primaryDisplay = screen.getPrimaryDisplay()
      const { width, height } = primaryDisplay.size
      const scaleFactor = primaryDisplay.scaleFactor || 1

      const sources = await desktopCapturer.getSources({
        types: ['window'],
        thumbnailSize: { width: Math.round(width * scaleFactor), height: Math.round(height * scaleFactor) }
      })

      const source = sources.find(s => s.id === sourceId)
      if (!source) {
        console.warn(`[Screenshot] Source ${sourceId} not found`)
        return null
      }

      const image = source.thumbnail
      if (image.isEmpty()) {
        console.warn('[Screenshot] Captured empty window image')
        return null
      }

      const imagePath = await this._saveImage(image, 'window')
      return {
        imagePath,
        dataURL: image.toDataURL(),
        width: image.getSize().width,
        height: image.getSize().height
      }
    } catch (err) {
      console.error('[Screenshot] captureWindow failed:', err.message)
      return null
    }
  }

  /**
   * Capture screen and run OCR on the image.
   * Returns { imagePath, dataURL, text, confidence, width, height } or null.
   */
  async captureAndOCR (opts = {}) {
    const capture = opts.sourceId
      ? await this.captureWindow(opts.sourceId)
      : await this.captureScreen()

    if (!capture) return null

    const ocrResult = await this.runOCR(capture.imagePath)
    return {
      ...capture,
      text: ocrResult?.text || '',
      confidence: ocrResult?.confidence || 0
    }
  }

  /**
   * Run OCR on an image file path or data URL.
   * Returns { text, confidence } or null if OCR unavailable.
   */
  async runOCR (imagePathOrDataURL) {
    const tess = loadTesseract()
    if (!tess) return null

    try {
      await this._ensureOCRWorker(tess)

      const { data } = await this._ocrWorker.recognize(imagePathOrDataURL)
      return {
        text: data.text?.trim() || '',
        confidence: data.confidence || 0
      }
    } catch (err) {
      console.error('[Screenshot] OCR failed:', err.message)
      return null
    }
  }

  /**
   * Shut down OCR worker if active.
   */
  async destroy () {
    if (this._ocrWorker) {
      try {
        await this._ocrWorker.terminate()
      } catch (_) { /* ignore */ }
      this._ocrWorker = null
      this._ocrReady = false
    }
  }

  // ── Internal ──

  async _ensureOCRWorker (tess) {
    if (this._ocrReady && this._ocrWorker) return

    this._ocrWorker = await tess.createWorker('eng', 1, {
      logger: (m) => {
        if (m.status === 'recognizing text') {
          // Could emit progress events here
        }
      }
    })
    this._ocrReady = true
    console.log('[Screenshot] OCR worker ready')
  }

  async _saveImage (nativeImage, prefix) {
    await mkdir(this._screenshotDir, { recursive: true })
    const ts = new Date().toISOString().replace(/[:.]/g, '-')
    const filename = `${prefix}-${ts}.png`
    const filepath = join(this._screenshotDir, filename)
    const buffer = nativeImage.toPNG()
    await writeFile(filepath, buffer)
    console.log(`[Screenshot] Saved: ${filepath} (${buffer.length} bytes)`)
    return filepath
  }
}
