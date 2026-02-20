# extension-shared/

Shared modules used across Chrome extensions in the extension architecture.

## Purpose

Chrome MV3 prohibits remote code loading (`script-src 'self'`). Instead of duplicating code, shared modules live here and are symlinked (dev) or copied (production) into each extension.

## Modules

| File | Source | Description |
|------|--------|-------------|
| `extractor-core.js` | Split from `extension/content_scripts/extractor.js` | Page extraction engine: 16 site-specific extractors, generic fallback, scroll detection, capture context management. No UI elements. |
| `script-runner-core.js` | Modified from `extension/content_scripts/script_runner.js` | Custom script execution engine with on-demand mode support. |
| `sandbox.html` | Moved from `extension/sandbox/sandbox.html` | Sandbox host page for CSP-bypassed script execution. |
| `sandbox.js` | Moved from `extension/sandbox/sandbox.js` | Sandbox runtime + RPC bridge. Zero chrome.* API calls. |
| `full-page-capture.js` | Extracted from `extension/background/service-worker.js` lines 461-642 | Full-page capture orchestration algorithm. ES module with parameterized chrome.* calls. |
| `operations-handler.js` | Canonical shared operations handler | Shared Chrome API operation handlers (10 ops: PING, LIST_TABS, GET_TAB_INFO, EXTRACT_CURRENT_PAGE, EXTRACT_TAB, CAPTURE_SCREENSHOT, CAPTURE_FULL_PAGE, CAPTURE_FULL_PAGE_WITH_OCR, CAPTURE_MULTI_TAB, EXECUTE_SCRIPT). ES module with parameterized `chromeApi` adapter + `captureState` mutex. Imports `full-page-capture.js`. |

## Usage

### Development (symlinks)

Each extension symlinks to files here:

```bash
# Current extension
ln -s ../../extension-shared/extractor-core.js extension/content_scripts/extractor-core.js
```

### Production (build.sh)

Run `build.sh` at repo root to replace symlinks with file copies for Chrome Web Store packaging.

## Consumer Extensions

| Extension | Modules Used |
|-----------|-------------|
| Current (`extension/`) | extractor-core.js, script-runner-core.js, sandbox.html, sandbox.js, full-page-capture.js |
| Iframe Sidepanel (`extension-iframe/`) | extractor-core.js, script-runner-core.js, sandbox.html, sandbox.js, full-page-capture.js, operations-handler.js — serves both regular browser tabs and sidepanel iframe contexts |

Note: `extension-headless/` is deprecated (see `extension-headless/DEPRECATED.md`). `extension-iframe/` now handles all contexts via externally_connectable transport.
