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

  // LRU eviction cap: keep at most this many snapshots in IndexedDB.
  // Sized for 20-30 active conversations; each can be up to MAX_HTML_CHARS (~4MB).
  // All cleared on logout via clearAll().
  const MAX_SNAPSHOTS = 30;

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

  /**
   * Evict oldest snapshots (by savedAt) once the store exceeds MAX_SNAPSHOTS.
   * Called after every successful put in saveNow. Best-effort: never rejects.
   */
  function evictOldest(db) {
    return new Promise(function (resolve) {
      try {
        var tx = db.transaction([STORE], "readwrite");
        var store = tx.objectStore(STORE);
        var countReq = store.count();
        countReq.onsuccess = function () {
          var total = countReq.result || 0;
          if (total <= MAX_SNAPSHOTS) { resolve(); return; }
          var toEvict = total - MAX_SNAPSHOTS;
          var idx = store.index("savedAt");
          var cursorReq = idx.openCursor(); // ascending by savedAt (oldest first)
          var evicted = 0;
          cursorReq.onsuccess = function (event) {
            var cursor = event.target.result;
            if (!cursor || evicted >= toEvict) { return; }
            cursor.delete();
            evicted++;
            cursor.continue();
          };
        };
        tx.oncomplete = function () { resolve(); };
        tx.onerror = function () { resolve(); };
      } catch (_e) {
        resolve();
      }
    });
  }

  function keyForConversation(conversationId) {
    return `conv:${String(conversationId)}`;
  }

  function getChatViewEl(convId) {
    if (convId) {
      var el = document.getElementById("chatView-" + convId);
      if (el) return el;
    }
    if (typeof TabManager !== 'undefined' && TabManager.focusedTabId) {
      var pane = document.getElementById("chatView-" + TabManager.focusedTabId);
      if (pane) return pane;
    }
    return document.getElementById("chatView");
  }

  // Build a content signature from a server message list. Uses
  // `message_short_hash` (derived from message TEXT by the backend, so it
  // changes whenever a message is edited) and falls back to message_id. This is
  // what makes snapshot validation content-aware: identity (count + last id) is
  // not enough because an edit keeps the same message_id but changes the text.
  function computeSigFromMessages(messages) {
    try {
      if (!Array.isArray(messages)) return "";
      return messages
        .map(function (m) {
          return String((m && (m.message_short_hash || m.message_id)) || "");
        })
        .join("|");
    } catch (_e) {
      return "";
    }
  }

  // Build the same signature from the rendered DOM. Each card carries the
  // server hash on `.message-ref-badge[data-msg-hash]`, mirroring
  // message_short_hash at render time, so the two signatures are comparable.
  function computeSigFromDom(chatView) {
    try {
      const cards = chatView.querySelectorAll(".message-card");
      const parts = [];
      cards.forEach(function (card) {
        const badge = card.querySelector(".message-ref-badge[data-msg-hash]");
        const hdr = card.querySelector(".card-header[message-id]");
        const hash = badge ? badge.getAttribute("data-msg-hash") || "" : "";
        const mid = hdr ? hdr.getAttribute("message-id") || "" : "";
        parts.push(hash || mid);
      });
      return parts.join("|");
    } catch (_e) {
      return "";
    }
  }

  function readDomMeta(convId) {
    try {
      const chatView = getChatViewEl(convId);
      if (!chatView) return { html: "", scrollTop: 0, lastMessageId: null, messageCount: 0, contentSig: "" };

      const html = chatView.innerHTML || "";
      const scrollTop = chatView.scrollTop || 0;

      // last message id from header attr (stable in your render pipeline)
      const headers = chatView.querySelectorAll(".message-card .card-header[message-id]");
      const lastHeader = headers && headers.length ? headers[headers.length - 1] : null;
      const lastMessageId = lastHeader ? (lastHeader.getAttribute("message-id") || null) : null;
      const messageCount = chatView.querySelectorAll(".message-card").length || 0;
      const contentSig = computeSigFromDom(chatView);

      return { html, scrollTop, lastMessageId, messageCount, contentSig };
    } catch (_e) {
      return { html: "", scrollTop: 0, lastMessageId: null, messageCount: 0, contentSig: "" };
    }
  }

  function applySnapshotToDom(snapshot, convId) {
    try {
      const chatView = getChatViewEl(convId);
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
      if (!(lastId && snapLastId && lastId === snapLastId)) return false;

      // Content-aware check: identity (count + last id) is NOT sufficient because
      // an edited message keeps its message_id but changes its text. Compare a
      // content signature derived from per-message hashes. Snapshots written
      // before this field existed (no contentSig) are treated as non-matching so
      // we safely re-render from fresh server data rather than restoring stale
      // text (this was the "edit reverts on refresh" bug).
      const freshSig = computeSigFromMessages(messages);
      const snapSig = typeof snapshotMeta.contentSig === "string" ? snapshotMeta.contentSig : "";
      if (!snapSig) return false;
      return snapSig === freshSig;
    } catch (_e) {
      return false;
    }
  }

  // Best-effort: delete a single conversation's cached snapshot. Call this
  // whenever a message is mutated (edited/reverted/deleted) so the next load
  // re-renders from authoritative server data instead of stale cached HTML.
  function invalidate(conversationId) {
    const d = $.Deferred();
    try {
      const cid = String(conversationId || "");
      if (!cid) { d.resolve(false); return d.promise(); }
      openDb()
        .then((db) => withStore(db, "readwrite", (store) => store.delete(keyForConversation(cid))))
        .then(() => d.resolve(true))
        .catch(() => d.resolve(false));
    } catch (_e) {
      d.resolve(false);
    }
    return d.promise();
  }

  // Clear ALL cached snapshots (e.g. on logout). IndexedDB is not cleared by
  // clearing cookies/localStorage, so logout must call this explicitly.
  function clearAll() {
    const d = $.Deferred();
    try {
      openDb()
        .then((db) => withStore(db, "readwrite", (store) => store.clear()))
        .then(() => d.resolve(true))
        .catch(() => d.resolve(false));
    } catch (_e) {
      d.resolve(false);
    }
    return d.promise();
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

      const meta = readDomMeta(cid);
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
        contentSig: meta.contentSig || "",
      };

      // Wait until MathJax has flushed typesetting for a stable layout, then snapshot.
      // (If MathJax isn't present, just write immediately.)
      const write = () => {
        openDb()
          .then((db) =>
            withStore(db, "readwrite", (store) => store.put(record))
              .then(() => evictOldest(db))
          )
          .catch(() => { /* best-effort */ });
      };

      if (!window._DISABLE_MATHJAX && window.MathJax && window.MathJax.Hub && window.MathJax.Hub.Queue) {
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
          const applied = applySnapshotToDom(snapshot, cid);
          if (!applied) return null;

          // Expose meta for the caller to decide whether to re-render after fetching messages.
          return {
            conversationId: cid,
            version: snapshot.version,
            savedAt: snapshot.savedAt,
            lastMessageId: snapshot.lastMessageId,
            messageCount: snapshot.messageCount,
            contentSig: typeof snapshot.contentSig === "string" ? snapshot.contentSig : "",
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
    invalidate: invalidate,
    clearAll: clearAll,
  };
})();


