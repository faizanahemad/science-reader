/**
 * desktop-bridge.js
 *
 * Provides window.desktopBridge — a set of methods that the Electron main/preload
 * process can call to trigger UI actions in the web interface.
 *
 * All methods are no-ops when not running in Electron (window.__isElectronDesktop is falsy).
 * When running in Electron, window.__isElectronDesktop is injected via contextBridge in preload.js.
 */
(function () {
  'use strict';

  function noop() {}

  // No-op bridge for non-Electron environments
  var noopBridge = {
    openGlobalDocsModal: noop,
    openPKBModal: noop,
    openPKBIngestFlow: noop,
    fillChatInput: noop,
    attachFileToChatInput: noop,
  };

  if (!window.__isElectronDesktop) {
    window.desktopBridge = noopBridge;
    return;
  }

  // Full bridge for Electron environment
  window.desktopBridge = {
    /**
     * Open the Global Docs modal, optionally pre-selecting a file path.
     * @param {string} [filePath] - Optional file path to pre-fill in the upload form
     */
    openGlobalDocsModal: function (filePathOrFile) {
      if (typeof globalDocsManager !== 'undefined' && globalDocsManager) {
        globalDocsManager.openModal();
        if (filePathOrFile) {
          setTimeout(function () {
            var fileInput = document.querySelector('#global-docs-modal input[type="file"]');
            if (!fileInput) return;

            if (filePathOrFile instanceof File) {
              // Programmatically set File on the input and trigger change
              var dt = new DataTransfer();
              dt.items.add(filePathOrFile);
              fileInput.files = dt.files;
              fileInput.dispatchEvent(new Event('change', { bubbles: true }));
            } else if (typeof filePathOrFile === 'string') {
              fileInput.dataset.prefilledPath = filePathOrFile;
              var pathDisplay = document.querySelector('#global-docs-modal .file-path-display');
              if (pathDisplay) {
                pathDisplay.textContent = filePathOrFile;
              }
            }
          }, 150);
        }
      } else {
        console.warn('[desktopBridge] globalDocsManager not available');
      }
    },

    /**
     * Open the PKB add-memory modal, optionally pre-filling text.
     * @param {string} [text] - Optional text to pre-fill
     */
    openPKBModal: function (text) {
      if (typeof pkbManager !== 'undefined' && pkbManager) {
        if (typeof pkbManager.openAddMemoryModal === 'function') {
          pkbManager.openAddMemoryModal(text || '');
        } else {
          // Fallback: open the modal by ID directly
          var modal = document.getElementById('pkb-claim-edit-modal');
          if (modal) {
            $(modal).modal('show');
            if (text) {
              var textarea = modal.querySelector('textarea');
              if (textarea) textarea.value = text;
            }
          }
        }
      } else {
        console.warn('[desktopBridge] pkbManager not available');
      }
    },

    /**
     * Trigger the PKB ingest flow with selected text.
     * @param {string} text - Text to ingest into PKB
     */
    openPKBIngestFlow: function (text) {
      // Reuse openPKBModal for now; can be extended later
      window.desktopBridge.openPKBModal(text);
    },

    /**
     * Fill the chat input with text (does not submit).
     * @param {string} text - Text to put in the chat input
     */
    fillChatInput: function (text) {
      // Look for chat input textarea using common selectors
      var chatInput = document.getElementById('chat-input') ||
                      document.querySelector('.chat-input-wrapper textarea') ||
                      document.querySelector('textarea[name="message"]');
      if (chatInput) {
        chatInput.value = text;
        // Trigger input event so any listeners (e.g. auto-resize) fire
        chatInput.dispatchEvent(new Event('input', { bubbles: true }));
        chatInput.focus();
      } else {
        console.warn('[desktopBridge] Chat input element not found');
      }
    },

    /**
     * Attach a file to the chat input.
     * @param {{ name: string, type: string, base64: string, size: number }} fileInfo
     */
    attachFileToChatInput: function (fileInfo) {
      try {
        // Convert base64 back to a File object and trigger the attachment flow
        var byteString = atob(fileInfo.base64);
        var ab = new ArrayBuffer(byteString.length);
        var ia = new Uint8Array(ab);
        for (var i = 0; i < byteString.length; i++) {
          ia[i] = byteString.charCodeAt(i);
        }
        var blob = new Blob([ab], { type: fileInfo.type });
        var file = new File([blob], fileInfo.name, { type: fileInfo.type });

        // Use existing file attachment infrastructure
        // setupPaperclipAndPageDrop sets up a global handler; check for it
        if (typeof window.attachFileToChat === 'function') {
          window.attachFileToChat(file);
        } else {
          // Fallback: create a DataTransfer and dispatch a drop event on chat input
          var dataTransfer = new DataTransfer();
          dataTransfer.items.add(file);
          var chatInput = document.getElementById('chat-input') ||
                          document.querySelector('.chat-input-wrapper textarea');
          if (chatInput) {
            var dropEvent = new DragEvent('drop', {
              bubbles: true,
              cancelable: true,
              dataTransfer: dataTransfer
            });
            chatInput.dispatchEvent(dropEvent);
          }
        }
      } catch (e) {
        console.error('[desktopBridge] attachFileToChatInput error:', e);
      }
    },
  };

  console.log('[desktopBridge] Electron bridge initialized');

  // ── M4.2: IPC listeners — main process → desktopBridge methods ──
  if (window.electronAPI) {
    window.electronAPI.on('bridge:open-global-docs', function (data) {
      if (data && data.base64 && data.name && data.type) {
        // File data from main process (drag-drop from sidebar/popbar)
        try {
          var byteString = atob(data.base64);
          var ab = new ArrayBuffer(byteString.length);
          var ia = new Uint8Array(ab);
          for (var i = 0; i < byteString.length; i++) {
            ia[i] = byteString.charCodeAt(i);
          }
          var blob = new Blob([ab], { type: data.type });
          var file = new File([blob], data.name, { type: data.type });
          window.desktopBridge.openGlobalDocsModal(file);
        } catch (e) {
          console.error('[desktopBridge] Error creating file from base64:', e);
          window.desktopBridge.openGlobalDocsModal(null);
        }
      } else {
        window.desktopBridge.openGlobalDocsModal(data && data.filePath);
      }
    });
    window.electronAPI.on('bridge:open-pkb-modal', function (data) {
      window.desktopBridge.openPKBModal(data && data.text);
    });
    window.electronAPI.on('bridge:open-pkb-ingest', function (data) {
      window.desktopBridge.openPKBIngestFlow(data && data.text);
    });
    window.electronAPI.on('bridge:fill-chat-input', function (data) {
      window.desktopBridge.fillChatInput(data && data.text);
    });
    window.electronAPI.on('bridge:attach-file', function (data) {
      window.desktopBridge.attachFileToChatInput(data);
    });
  }

  // ── M4.1: Drag-and-drop interception for non-chat-input areas ──
  ;(function setupChatDropInterception () {
    var dragCounter = 0;

    document.addEventListener('dragenter', function (e) {
      dragCounter++;
      if (e.dataTransfer && e.dataTransfer.types.indexOf('Files') !== -1) {
        if (!isOverChatInput(e.target)) {
          document.body.classList.add('desktop-drop-active');
        }
      }
    });

    document.addEventListener('dragleave', function () {
      dragCounter--;
      if (dragCounter <= 0) {
        dragCounter = 0;
        document.body.classList.remove('desktop-drop-active');
      }
    });

    document.addEventListener('dragover', function (e) {
      if (e.dataTransfer && e.dataTransfer.types.indexOf('Files') !== -1) {
        if (!isOverChatInput(e.target)) {
          e.preventDefault();
          e.dataTransfer.dropEffect = 'copy';
        }
      }
    });

    document.addEventListener('drop', function (e) {
      dragCounter = 0;
      document.body.classList.remove('desktop-drop-active');

      // Only intercept drops OUTSIDE the chat input area
      if (isOverChatInput(e.target)) return; // Let existing handler work

      if (!e.dataTransfer || !e.dataTransfer.files || e.dataTransfer.files.length === 0) return;

      e.preventDefault();
      e.stopPropagation();

      var file = e.dataTransfer.files[0];
      window.desktopBridge.openGlobalDocsModal(file);
    });

    function isOverChatInput (el) {
      while (el) {
        if (el.id === 'chat-input' || el.id === 'chat-input-wrapper' ||
            (el.classList && (el.classList.contains('chat-input-wrapper') ||
             el.classList.contains('attachment-preview-container') ||
             el.classList.contains('page-drop-zone')))) {
          return true;
        }
        el = el.parentElement;
      }
      return false;
    }
  })();

  // Inject drop zone CSS
  var style = document.createElement('style');
  style.textContent = 'body.desktop-drop-active { outline: 2px dashed #89b4fa !important; outline-offset: -4px; }';
  document.head.appendChild(style);
})();
