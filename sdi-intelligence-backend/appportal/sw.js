/* SDI Intelligence app portal — service worker.
 *
 * Strategy:
 *   pages  (html)            → network-first, cached copy only when offline
 *   icons, manifest          → cache-first, refreshed in the background
 *   /api/services (catalogue)→ network-first, falling back to cache when offline
 *   other /api/*, /auth/*    → never touched
 *
 * Deliberately NOT cached: anything under /api/files or /api/file. Those serve
 * real company documents from the shares and must never sit in a device cache.
 */
const VERSION = 'sdi-app-v4';   // v4: pages network-first, so a deploy shows at once
const SHELL = [
  './',
  './index.html',
  './manifest.webmanifest',
  './icon-192.png',
  './icon-512.png'
];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(VERSION).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== VERSION).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;

  const url = new URL(req.url);
  if (url.origin !== location.origin) return;

  // Catalogue: network-first so a published change shows up straight away.
  // This is the ONLY API traffic the worker may touch.
  if (url.pathname.startsWith('/api/services') || url.pathname.endsWith('services.json')) {
    e.respondWith(
      fetch(req)
        .then(res => {
          const copy = res.clone();
          caches.open(VERSION).then(c => c.put(req, copy));
          return res;
        })
        .catch(() => caches.match(req))
    );
    return;
  }

  // Everything else under /api/ or /auth/ is live state — sign-in status,
  // records, journal. Serving yesterday's copy of any of it is worse than an
  // honest network error, so the worker stays out of the way entirely.
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/auth/')) return;

  // Pages: network-first. Cache-first served the previous version of a page
  // after every deploy; the cached copy is now only the offline fallback.
  if (req.mode === 'navigate' || url.pathname.endsWith('.html') || url.pathname.endsWith('/')) {
    e.respondWith(
      fetch(req)
        .then(res => {
          if (res && res.ok) { const copy = res.clone(); caches.open(VERSION).then(c => c.put(req, copy)); }
          return res;
        })
        .catch(() => caches.match(req))
    );
    return;
  }

  // Icons and the manifest: cache-first, with a background refresh.
  e.respondWith(
    caches.match(req).then(hit => {
      const net = fetch(req).then(res => {
        if (res && res.ok) {
          const copy = res.clone();
          caches.open(VERSION).then(c => c.put(req, copy));
        }
        return res;
      }).catch(() => hit);
      return hit || net;
    })
  );
});
