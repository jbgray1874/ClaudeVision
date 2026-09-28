/* SDI Intelligence app portal — service worker.
 *
 * Strategy:
 *   shell  (html/css/icons)  → cache-first, refreshed in the background
 *   /api/* (the catalogue)   → network-first, falling back to cache when offline
 *
 * Deliberately NOT cached: anything under /api/files or /api/file. Those serve
 * real company documents from the shares and must never sit in a device cache.
 */
const VERSION = 'sdi-app-v1';
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

  // Never cache file-share traffic.
  if (url.pathname.startsWith('/api/file')) return;

  // Catalogue: network-first so a published change shows up straight away.
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

  // Shell: cache-first, with a background refresh.
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
