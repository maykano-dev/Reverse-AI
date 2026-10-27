/* ReverseAI service worker — app shell only.
   Never cache API responses, SSE streams, uploads, previews, or downloads. */
const VERSION = "rvai-v15";
const SHELL = [
  "/",
  "/app.js",
  "/style.css",
  "/manifest.webmanifest",
  "/icon.svg",
  "/vendor/marked.min.js",
  "/vendor/purify.min.js",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(VERSION).then((cache) => cache.addAll(SHELL)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== VERSION).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

function isShell(url) {
  const p = url.pathname;
  if (p === "/" || p === "/app.js" || p === "/style.css" || p === "/icon.svg" ||
      p === "/manifest.webmanifest") return true;
  return p.startsWith("/vendor/");
}

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  if (!isShell(url)) return; // API, SSE, preview, files: always network

  // Network-first: always serve the latest shell, falling back to cache only
  // when offline. (Cache-first served stale app.js/style.css after updates.)
  event.respondWith(
    fetch(req).then((res) => {
      const copy = res.clone();
      caches.open(VERSION).then((cache) => cache.put(req, copy)).catch(() => {});
      return res;
    }).catch(() =>
      caches.match(req).then((hit) =>
        hit || (req.mode === "navigate" ? caches.match("/") : undefined))
    )
  );
});
