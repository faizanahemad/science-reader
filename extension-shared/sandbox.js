/**
 * AI Assistant Sandbox
 *
 * Runs user-provided script code in a sandboxed extension page so we can safely use
 * `new Function`/eval-like compilation without requiring 'unsafe-eval' in the main extension CSP.
 *
 * IMPORTANT:
 * - This environment has NO access to the page DOM.
 * - User scripts MUST use `aiAssistant.dom.*`, `aiAssistant.clipboard.*`, etc.
 * - All aiAssistant methods are proxied to the content script via postMessage RPC.
 */

(() => {
  'use strict';

  const TAG = '[Sandbox]';
  const PARENT_ORIGIN = '*'; // Parent (content script) validates our origin; we accept all.

  /** @type {Map<string, {resolve: Function, reject: Function, timeoutId: number}>} */
  const pendingRpc = new Map();

  /** @type {Map<string, {handlers: any, parse: any}>} */
  const scriptRegistry = new Map();

  function log(...args) {
    // eslint-disable-next-line no-console
    console.log(TAG, ...args);
  }

  function postToParent(message) {
    window.parent.postMessage({ __aiAssistantSandbox: true, ...message }, PARENT_ORIGIN);
  }

  function rpc(scriptId, method, args) {
    const requestId = `rpc_${Date.now()}_${Math.random().toString(16).slice(2)}`;
    return new Promise((resolve, reject) => {
      const timeoutId = window.setTimeout(() => {
        pendingRpc.delete(requestId);
        reject(new Error(`RPC timeout: ${method}`));
      }, 15000);

      pendingRpc.set(requestId, { resolve, reject, timeoutId });
      postToParent({
        type: 'RPC',
        requestId,
        scriptId,
        method,
        args
      });
    });
  }

  function createAiAssistant(scriptId) {
    return {
      dom: {
        query: (selector) => rpc(scriptId, 'dom.query', [selector]),
        queryAll: (selector) => rpc(scriptId, 'dom.queryAll', [selector]),
        exists: (selector) => rpc(scriptId, 'dom.exists', [selector]),
        count: (selector) => rpc(scriptId, 'dom.count', [selector]),
        getText: (selector) => rpc(scriptId, 'dom.getText', [selector]),
        getHtml: (selector) => rpc(scriptId, 'dom.getHtml', [selector]),
        getAttr: (selector, name) => rpc(scriptId, 'dom.getAttr', [selector, name]),
        setAttr: (selector, name, value) => rpc(scriptId, 'dom.setAttr', [selector, name, value]),
        getValue: (selector) => rpc(scriptId, 'dom.getValue', [selector]),
        waitFor: (selector, timeout) => rpc(scriptId, 'dom.waitFor', [selector, timeout]),
        hide: (selector) => rpc(scriptId, 'dom.hide', [selector]),
        show: (selector) => rpc(scriptId, 'dom.show', [selector]),
        setHtml: (selector, html) => rpc(scriptId, 'dom.setHtml', [selector, html]),
        scrollIntoView: (selector, behavior) => rpc(scriptId, 'dom.scrollIntoView', [selector, behavior]),
        focus: (selector) => rpc(scriptId, 'dom.focus', [selector]),
        blur: (selector) => rpc(scriptId, 'dom.blur', [selector]),
        click: (selector) => rpc(scriptId, 'dom.click', [selector]),
        setValue: (selector, value) => rpc(scriptId, 'dom.setValue', [selector, value]),
        type: (selector, text, opts) => rpc(scriptId, 'dom.type', [selector, text, opts]),
        remove: (selector) => rpc(scriptId, 'dom.remove', [selector]),
        addClass: (selector, className) => rpc(scriptId, 'dom.addClass', [selector, className]),
        removeClass: (selector, className) => rpc(scriptId, 'dom.removeClass', [selector, className]),
        toggleClass: (selector, className, force) => rpc(scriptId, 'dom.toggleClass', [selector, className, force])
      },
      clipboard: {
        copy: (text) => rpc(scriptId, 'clipboard.copy', [text]),
        copyHtml: (html) => rpc(scriptId, 'clipboard.copyHtml', [html])
      },
      ui: {
        showToast: (message, type) => rpc(scriptId, 'ui.showToast', [message, type]),
        showModal: (title, content) => rpc(scriptId, 'ui.showModal', [title, content]),
        closeModal: () => rpc(scriptId, 'ui.closeModal', [])
      },
      llm: {
        ask: (prompt) => rpc(scriptId, 'llm.ask', [prompt]),
        askStreaming: async (prompt, onChunk) => {
          // Not truly streaming through this bridge yet; best-effort.
          const resp = await rpc(scriptId, 'llm.ask', [prompt]);
          if (typeof onChunk === 'function') onChunk(resp);
        }
      },
      storage: {
        get: (key) => rpc(scriptId, 'storage.get', [key]),
        set: (key, value) => rpc(scriptId, 'storage.set', [key, value])
      }
    };
  }

  function safeSerialize(value) {
    // Ensure result can be posted across windows.
    if (value === undefined) return null;
    try {
      return structuredClone(value);
    } catch {
      try {
        return JSON.parse(JSON.stringify(value));
      } catch {
        return String(value);
      }
    }
  }

  async function handleExecute(message) {
    const { requestId, scriptId, code } = message;
    try {
      // Reset exported globals for this run
      window.__scriptHandlers = undefined;
      window.__parseContent = undefined;

      const aiAssistant = createAiAssistant(scriptId);

      // Compile + execute. User script should set window.__scriptHandlers (and optionally __parseContent).
      // eslint-disable-next-line no-new-func
      const fn = new Function('aiAssistant', `"use strict";\n${code}\n;return true;`);
      fn(aiAssistant);

      const handlers = window.__scriptHandlers || null;
      const parse = window.__parseContent || null;

      const handlerNames = handlers && typeof handlers === 'object'
        ? Object.keys(handlers).filter((k) => typeof handlers[k] === 'function')
        : [];

      scriptRegistry.set(scriptId, { handlers, parse });

      postToParent({
        type: 'RESPONSE',
        requestId,
        ok: true,
        result: { handlerNames }
      });
    } catch (e) {
      postToParent({
        type: 'RESPONSE',
        requestId,
        ok: false,
        error: e?.message || String(e)
      });
    }
  }

  async function handleInvoke(message) {
    const { requestId, scriptId, handlerName } = message;
    try {
      const entry = scriptRegistry.get(scriptId);
      if (!entry || !entry.handlers) {
        throw new Error(`Script not loaded: ${scriptId}`);
      }
      const fn = entry.handlers[handlerName];
      if (typeof fn !== 'function') {
        throw new Error(`Handler not found: ${handlerName}`);
      }
      const res = await fn();
      postToParent({
        type: 'RESPONSE',
        requestId,
        ok: true,
        result: safeSerialize(res)
      });
    } catch (e) {
      postToParent({
        type: 'RESPONSE',
        requestId,
        ok: false,
        error: e?.message || String(e)
      });
    }
  }

  function handleClearAll(message) {
    const { requestId } = message;
    scriptRegistry.clear();
    postToParent({
      type: 'RESPONSE',
      requestId,
      ok: true,
      result: true
    });
  }

  window.addEventListener('message', (event) => {
    const data = event.data;
    if (!data || data.__aiAssistantSandbox !== true) return;

    // Responses to RPC calls (sandbox -> parent -> sandbox)
    if (data.type === 'RPC_RESPONSE') {
      const pending = pendingRpc.get(data.requestId);
      if (!pending) return;
      pendingRpc.delete(data.requestId);
      window.clearTimeout(pending.timeoutId);
      if (data.ok) pending.resolve(data.result);
      else pending.reject(new Error(data.error || 'RPC failed'));
      return;
    }

    // Requests from parent (content script)
    if (data.type === 'EXECUTE') {
      handleExecute(data);
    } else if (data.type === 'INVOKE') {
      handleInvoke(data);
    } else if (data.type === 'CLEAR_ALL') {
      handleClearAll(data);
    }
  });

  // Handshake
  log('Sandbox ready');
  postToParent({ type: 'READY' });
})();


