const CACHE = 'fairy-shell-v22';
const SHELL = [
  '/',
  '/assets/style.css',
  '/assets/app.js',
  '/assets/p1.js',
  '/assets/knowledge.js',
  '/assets/assessments.js',
  '/assets/p3.js',
  '/assets/p5.js',
  '/assets/manifest.webmanifest',
  '/assets/fairy-icon.svg',
  '/assets/fairy-icon-192.png',
  '/assets/fairy-icon-512.png',
  '/assets/apple-touch-icon.png',
];

self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys => Promise.all(keys.filter(key => key !== CACHE).map(key => caches.delete(key))))
  );
  self.clients.claim();
});

self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);
  if (event.request.method !== 'GET' || url.origin !== self.location.origin || url.pathname.startsWith('/v2/')) return;
  event.respondWith(
    fetch(event.request)
      .then(response => {
        if (response.ok) {
          const copy = response.clone();
          caches.open(CACHE).then(cache => cache.put(event.request, copy));
        }
        return response;
      })
      .catch(async () => {
        const cached = await caches.match(event.request);
        if (cached) return cached;
        if (event.request.mode === 'navigate') return caches.match('/');
        return Response.error();
      })
  );
});
