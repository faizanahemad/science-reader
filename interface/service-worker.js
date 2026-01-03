/* eslint-disable no-restricted-globals */
/**
 * Service Worker for the `/interface/*` UI shell.
 *
 * Design goals (per project plan):
 * - Cache only the same-origin "app shell" assets under `/interface/*` and `/static/*`.
 * - Treat ALL API endpoints (see `endpoints/external_api.md`) as NetworkOnly.
 * - Do NOT cache cross-origin CDN assets (MathJax/Marked/etc) initially to avoid staleness/update risk.
 * - Use NetworkFirst for navigations under `/interface/*` (avoid HTML/JS mismatch), with offline fallback to cached shell.
 */

const DEBUG = false;

const CACHE_VERSION = "v6";
const UI_SHELL_CACHE = `ui-shell-${CACHE_VERSION}`;
const META_CACHE = `meta-${CACHE_VERSION}`;

// TTL policy (milliseconds). Used as a safety net so stale assets eventually refresh
// even if CACHE_VERSION isn't bumped.
const TTL_6H = 6 * 60 * 60 * 1000;

// Conservative allowlist for third-party assets (scripts/styles/fonts) referenced in `interface/interface.html`.
// We only cache asset-like requests (script/style/font/image) from these hosts.
const CDN_ALLOWLIST_HOSTS = new Set([
  "cdn.jsdelivr.net",
  "cdnjs.cloudflare.com",
  "code.jquery.com",
  "cdn.datatables.net",
  "gitcdn.github.io",
  // NOTE: these are effectively "unversioned/latest" endpoints in your HTML.
  // We allow caching them, but they will use TTL refresh rather than long-lived caching.
  "mozilla.github.io",
  "laingsimon.github.io",
]);

// Deterministic precache list: only same-origin assets that are part of your UI bundle.
// Note: `interface/interface.html` references local assets as `interface/...`, which resolves to
// `/interface/interface/...` when the page URL is `/interface` or `/interface/<conversation_id>`.
const PRECACHE_URLS = [
  // UI shell (HTML). Cached for offline fallback only; navigations are still NetworkFirst.
  "/interface",

  // Local CSS
  "/interface/interface/style.css",
  "/interface/interface/workspace-styles.css",

  // Local JS (referenced by interface/interface.html)
  "/interface/interface/parseMessageForCheckBoxes.js",
  "/interface/interface/common.js",
  "/interface/interface/rendered-state-manager.js",
  "/interface/interface/gamification.js",
  "/interface/interface/common-chat.js",
  "/interface/interface/markdown-editor.js",
  "/interface/interface/interface.js",
  "/interface/interface/codemirror.js",
  "/interface/interface/doubt-manager.js",
  "/interface/interface/clarifications-manager.js",
  "/interface/interface/temp-llm-manager.js",
  "/interface/interface/context-menu-manager.js",
  "/interface/interface/prompt-manager.js",
  "/interface/interface/pkb-manager.js",
  "/interface/interface/chat.js",
  "/interface/interface/workspace-manager.js",
  "/interface/interface/audio_process.js",

  // PWA artifacts
  "/interface/manifest.json",
  "/interface/icons/app-icon.svg",
  "/interface/icons/maskable-icon.svg",
];

const ASSET_EXTENSIONS = new Set([
  ".js",
  ".css",
  ".png",
  ".jpg",
  ".jpeg",
  ".gif",
  ".svg",
  ".ico",
  ".woff",
  ".woff2",
  ".ttf",
  ".otf",
  ".map",
  ".json",
]);

function log(...args) {
  if (DEBUG) console.log("[sw]", ...args);
}

function isSameOrigin(url) {
  return url.origin === self.location.origin;
}

function hasAssetExtension(pathname) {
  const idx = pathname.lastIndexOf(".");
  if (idx === -1) return false;
  return ASSET_EXTENSIONS.has(pathname.slice(idx).toLowerCase());
}

function isInterfaceOrStaticPath(pathname) {
  return pathname.startsWith("/interface/") || pathname.startsWith("/static/");
}

function isAssetDestination(request) {
  return (
    request.destination === "script" ||
    request.destination === "style" ||
    request.destination === "font" ||
    request.destination === "image"
  );
}

function metaKeyFor(urlHref) {
  // Use a synthetic URL to avoid colliding with real network requests.
  return new Request(`https://sw-meta.invalid/${encodeURIComponent(urlHref)}`);
}

async function getCachedTimestamp(urlHref) {
  try {
    const metaCache = await caches.open(META_CACHE);
    const metaResp = await metaCache.match(metaKeyFor(urlHref));
    if (!metaResp) return null;
    const data = await metaResp.json();
    return typeof data?.ts === "number" ? data.ts : null;
  } catch (_e) {
    return null;
  }
}

async function setCachedTimestamp(urlHref, ts) {
  try {
    const metaCache = await caches.open(META_CACHE);
    await metaCache.put(
      metaKeyFor(urlHref),
      new Response(JSON.stringify({ ts }), {
        headers: { "Content-Type": "application/json" },
      })
    );
  } catch (_e) {
    // best-effort
  }
}

function isFresh(ts, ttlMs) {
  if (typeof ts !== "number") return false;
  return Date.now() - ts <= ttlMs;
}

async function cachePutWithMeta(cache, request, response) {
  await cache.put(request, response);
  await setCachedTimestamp(request.url, Date.now());
}

self.addEventListener("install", (event) => {
  event.waitUntil(
    (async () => {
      log("install");
      const cache = await caches.open(UI_SHELL_CACHE);

      // Cache each URL individually (avoids install failure if any single fetch fails).
      await Promise.all(
        PRECACHE_URLS.map(async (url) => {
          try {
            const req = new Request(url, { cache: "reload" });
            const resp = await fetch(req);
            if (!resp.ok) return;
            // Avoid caching opaque/cross-origin and redirects.
            if (resp.type !== "basic" || resp.redirected) return;
            await cachePutWithMeta(cache, req, resp);
          } catch (_e) {
            // Best-effort: cache whatever we can.
          }
        })
      );

      // Conservative default: don't force-activate; next navigation will pick up the new SW.
      // (No skipWaiting here on purpose.)
    })()
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      log("activate");
      const keys = await caches.keys();
      await Promise.all(
        keys.map((key) => {
          if (key.startsWith("ui-shell-") && key !== UI_SHELL_CACHE) {
            return caches.delete(key);
          }
          if (key.startsWith("meta-") && key !== META_CACHE) {
            return caches.delete(key);
          }
          return undefined;
        })
      );
    })()
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;

  // Never interfere with non-GET requests (uploads/POST streaming/etc).
  if (req.method !== "GET") return;

  const url = new URL(req.url);
  const sameOrigin = isSameOrigin(url);

  // CDN caching (optional, conservative): only cache asset-like requests from known hosts.
  if (!sameOrigin) {
    if (!CDN_ALLOWLIST_HOSTS.has(url.hostname)) return;
    if (!isAssetDestination(req)) return;

    event.respondWith(
      (async () => {
        const cache = await caches.open(UI_SHELL_CACHE);
        const cached = await cache.match(req);
        const ts = await getCachedTimestamp(req.url);

        // If we have a fresh cached entry, serve it.
        if (cached && isFresh(ts, TTL_6H)) return cached;

        // Otherwise try network and refresh cache; fall back to stale cache if offline.
        try {
          const resp = await fetch(req);
          // Opaque/cors responses are safe to store and replay; avoid redirects.
          if (resp.ok && !resp.redirected) {
            cachePutWithMeta(cache, req, resp.clone()).catch(() => {});
          }
          return resp;
        } catch (_e) {
          if (cached) return cached;
          return new Response("Offline", { status: 503, headers: { "Content-Type": "text/plain" } });
        }
      })()
    );
    return;
  }

  // Special-case: never cache the SW script itself (avoid update weirdness).
  if (url.pathname === "/interface/service-worker.js") return;

  // Only handle app-shell paths; everything else remains NetworkOnly (covers all APIs).
  if (!isInterfaceOrStaticPath(url.pathname) && url.pathname !== "/interface") return;

  // Navigations: NetworkFirst to avoid old HTML referencing new/old assets incorrectly.
  const isNavigation = req.mode === "navigate" || req.destination === "document";
  if (isNavigation) {
    event.respondWith(
      (async () => {
        try {
          const netResp = await fetch(req);
          // Cache latest shell HTML for offline fallback only.
          if (netResp.ok && netResp.type === "basic" && !netResp.redirected) {
            const cache = await caches.open(UI_SHELL_CACHE);
            cachePutWithMeta(cache, req, netResp.clone()).catch(() => {});
          }
          return netResp;
        } catch (_e) {
          const cache = await caches.open(UI_SHELL_CACHE);
          // Fallback to cached shell HTML, then to any cached response for this request.
          return (
            (await cache.match("/interface")) ||
            (await cache.match(req)) ||
            new Response("Offline", { status: 503, headers: { "Content-Type": "text/plain" } })
          );
        }
      })()
    );
    return;
  }

  // Static assets: CacheFirst (for same-origin `/interface/*` or `/static/*` with asset extensions).
  if (hasAssetExtension(url.pathname)) {
    event.respondWith(
      (async () => {
        const cache = await caches.open(UI_SHELL_CACHE);
        const cached = await cache.match(req);
        const ts = await getCachedTimestamp(req.url);

        // Serve from cache if fresh. If stale, try network refresh but fall back to cached.
        if (cached && isFresh(ts, TTL_6H)) return cached;

        try {
          const resp = await fetch(req);
          if (resp.ok && resp.type === "basic" && !resp.redirected) {
            cachePutWithMeta(cache, req, resp.clone()).catch(() => {});
          }
          return resp;
        } catch (_e) {
          if (cached) return cached;
          throw _e;
        }
      })()
    );
    return;
  }

  // Default: NetworkOnly for any other same-origin GET under `/interface/*` or `/static/*`.
});

