/* Sentinel XO — Service Worker
   Estrategia: estáticos cache-first; API nunca se cachea; navegación
   network-first (datos siempre frescos) con respaldo offline. */
const CACHE  = 'sentinel-xo-v1';
const ASSETS = [
  '/static/pwa/icon-192.png',
  '/static/pwa/icon-512.png'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(ASSETS)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;

  const url = new URL(req.url);

  // Nunca cachear API ni orígenes externos
  if (url.origin !== self.location.origin || url.pathname.startsWith('/api/')) return;

  // Estáticos: cache-first
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(
      caches.match(req).then((r) => r || fetch(req).then((resp) => {
        const copy = resp.clone();
        caches.open(CACHE).then((c) => c.put(req, copy));
        return resp;
      }))
    );
    return;
  }

  // Navegación y resto: network-first, cache como respaldo offline
  event.respondWith(
    fetch(req).then((resp) => {
      if (req.mode === 'navigate') {
        const copy = resp.clone();
        caches.open(CACHE).then((c) => c.put(req, copy));
      }
      return resp;
    }).catch(() => caches.match(req).then((r) => r || caches.match('/dashboard/')))
  );
});
