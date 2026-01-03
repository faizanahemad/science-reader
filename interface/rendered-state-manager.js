/* eslint-disable no-undef */
/**
 * Rendered-state persistence for conversations (DOM snapshot + scroll) using IndexedDB.
 *
 * Goals:
 * - Restore a conversation view instantly on load (especially on mobile/PWA).
 * - Keep APIs NetworkOnly (we still fetch messages), but skip expensive re-render if unchanged.
 * - Versioned invalidation: bump RENDER_SNAPSHOT_VERSION when UI rendering logic changes.
 *
 * Storage format:
 * - key: "conv:<conversationId>"
 * - { conversationId, version, savedAt, html, scrollTop, lastMessageId, messageCount }
 */

(function () {
  "use strict";

  // IMPORTANT: bump this when UI rendering changes in a way that makes old DOM snapshots unsafe.
  // Keep it aligned with `CACHE_VERSION` in `interface/service-worker.js` when you want.
  const RENDER_SNAPSHOT_VERSION =
    (window && window.UI_CACHE_VERSION) ? String(window.UI_CACHE_VERSION) : "v1";

  const DB_NAME = "science-chat-rendered-state";
  const DB_VERSION = 1;
  const STORE = "snapshots";

  // Guardrail: avoid storing enormous conversations that could blow up storage.
  const MAX_HTML_CHARS = 4_000_000; // ~4MB as UTF-16-ish (rough), best-effort

  function openDb() {
    return new Promise((resolve, reject) => {
      try {
        const req = indexedDB.open(DB_NAME, DB_VERSION);
        req.onupgradeneeded = function (event) {
          const db = event.target.result;
          if (!db.objectStoreNames.contains(STORE)) {
            const os = db.createObjectStore(STORE, { keyPath: "key" });
            os.createIndex("conversationId", "conversationId", { unique: false });
            os.createIndex("savedAt", "savedAt", { unique: false });
          }
        };
        req.onsuccess = function () {
          resolve(req.result);
        };
        req.onerror = function () {
          reject(req.error || new Error("IndexedDB open failed"));
        };
      } catch (e) {
        reject(e);
      }
    });
  }

  function withStore(db, mode, fn) {
    return new Promise((resolve, reject) => {
      try {
        const tx = db.transaction([STORE], mode);
        const store = tx.objectStore(STORE);
        let out;
        try {
          out = fn(store);
        } catch (e) {
          reject(e);
          return;
        }
        tx.oncomplete = function () {
          resolve(out);
        };
        tx.onerror = function () {
          reject(tx.error || new Error("IndexedDB transaction failed"));
        };
      } catch (e) {
        reject(e);
      }
    });
  }

  function keyForConversation(conversationId) {
    return `conv:${String(conversationId)}`;
  }

  function getChatViewEl() {
    return document.getElementById("chatView");
  }

  function readDomMeta() {
    try {
      const chatView = getChatViewEl();
      if (!chatView) return { html: "", scrollTop: 0, lastMessageId: null, messageCount: 0 };

      const html = chatView.innerHTML || "";
      const scrollTop = chatView.scrollTop || 0;

      // last message id from header attr (stable in your render pipeline)
      const headers = chatView.querySelectorAll(".message-card .card-header[message-id]");
      const lastHeader = headers && headers.length ? headers[headers.length - 1] : null;
      const lastMessageId = lastHeader ? (lastHeader.getAttribute("message-id") || null) : null;
      const messageCount = chatView.querySelectorAll(".message-card").length || 0;

      return { html, scrollTop, lastMessageId, messageCount };
    } catch (_e) {
      return { html: "", scrollTop: 0, lastMessageId: null, messageCount: 0 };
    }
  }

  function applySnapshotToDom(snapshot) {
    try {
      const chatView = getChatViewEl();
      if (!chatView) return false;
      if (!snapshot || typeof snapshot.html !== "string") return false;

      chatView.innerHTML = snapshot.html;
      // Restore scroll after DOM write
      requestAnimationFrame(() => {
        try {
          chatView.scrollTop = snapshot.scrollTop || 0;
        } catch (_e) { /* ignore */ }
      });
      return true;
    } catch (_e) {
      return false;
    }
  }

  function matchesMessages(snapshotMeta, messages) {
    try {
      if (!snapshotMeta) return false;
      if (!Array.isArray(messages)) return false;
      if (messages.length !== snapshotMeta.messageCount) return false;
      const last = messages.length ? messages[messages.length - 1] : null;
      const lastId = last ? String(last.message_id || "") : "";
      const snapLastId = snapshotMeta.lastMessageId ? String(snapshotMeta.lastMessageId) : "";
      return lastId && snapLastId && (lastId === snapLastId);
    } catch (_e) {
      return false;
    }
  }

  // Debounced saves per conversation id
  const saveTimers = new Map();

  function scheduleSave(conversationId, delayMs = 1200) {
    try {
      const cid = String(conversationId || "");
      if (!cid) return;
      if (saveTimers.has(cid)) {
        clearTimeout(saveTimers.get(cid));
      }
      const t = setTimeout(() => {
        saveTimers.delete(cid);
        saveNow(cid);
      }, delayMs);
      saveTimers.set(cid, t);
    } catch (_e) { /* ignore */ }
  }

  function saveNow(conversationId) {
    try {
      const cid = String(conversationId || "");
      if (!cid) return;

      const meta = readDomMeta();
      if (!meta.html || meta.html.length < 10) return;
      if (meta.html.length > MAX_HTML_CHARS) return;

      const record = {
        key: keyForConversation(cid),
        conversationId: cid,
        version: RENDER_SNAPSHOT_VERSION,
        savedAt: Date.now(),
        html: meta.html,
        scrollTop: meta.scrollTop,
        lastMessageId: meta.lastMessageId,
        messageCount: meta.messageCount,
      };

      // Wait until MathJax has flushed typesetting for a stable layout, then snapshot.
      // (If MathJax isn't present, just write immediately.)
      const write = () => {
        openDb()
          .then((db) => withStore(db, "readwrite", (store) => store.put(record)))
          .catch(() => { /* best-effort */ });
      };

      if (window.MathJax && window.MathJax.Hub && window.MathJax.Hub.Queue) {
        try {
          window.MathJax.Hub.Queue(write);
          return;
        } catch (_e) {
          // fall through
        }
      }
      write();
    } catch (_e) {
      // best-effort
    }
  }

  function restore(conversationId) {
    const d = $.Deferred();
    try {
      const cid = String(conversationId || "");
      if (!cid) {
        d.resolve(null);
        return d.promise();
      }

      openDb()
        .then((db) =>
          withStore(db, "readonly", (store) => {
            return new Promise((resolve, reject) => {
              const req = store.get(keyForConversation(cid));
              req.onsuccess = function () { resolve(req.result || null); };
              req.onerror = function () { reject(req.error || new Error("get failed")); };
            });
          })
        )
        .then((snapshot) => {
          if (!snapshot) return null;
          // Version mismatch => ignore (and try to delete best-effort)
          if (String(snapshot.version || "") !== String(RENDER_SNAPSHOT_VERSION)) {
            try {
              openDb()
                .then((db) => withStore(db, "readwrite", (store) => store.delete(keyForConversation(cid))))
                .catch(() => { /* ignore */ });
            } catch (_e) { /* ignore */ }
            return null;
          }
          const applied = applySnapshotToDom(snapshot);
          if (!applied) return null;

          // Expose meta for the caller to decide whether to re-render after fetching messages.
          return {
            conversationId: cid,
            version: snapshot.version,
            savedAt: snapshot.savedAt,
            lastMessageId: snapshot.lastMessageId,
            messageCount: snapshot.messageCount,
          };
        })
        .then((meta) => d.resolve(meta))
        .catch(() => d.resolve(null));
    } catch (_e) {
      d.resolve(null);
    }
    return d.promise();
  }

  window.RenderedStateManager = {
    version: RENDER_SNAPSHOT_VERSION,
    restore: restore,
    scheduleSave: scheduleSave,
    saveNow: saveNow,
    matchesMessages: matchesMessages,
  };
})();


