// public/sw.js
// Minimal, safe Service Worker for Tech Tips Hub:
// - Network-first for HTML navigations and /api/* so content stays fresh.
// - Conservative stale-while-revalidate for static shell assets.
// - Cleans up old cache versions on activate.

const CACHE_NAME = 'techtips-hub-v1';
const SHELL_ASSETS = [
  '/manifest.webmanifest',
  '/favicon.svg',
  '/js/actions.js',
  '/js/tip-card.js',
];

function isStaticShellAsset(pathname) {
  return (
    pathname.startsWith('/_astro/') ||
    pathname.startsWith('/js/') ||
    pathname.startsWith('/favicons/') ||
    pathname === '/favicon.svg' ||
    pathname === '/manifest.webmanifest' ||
    pathname === '/og-image.png'
  );
}

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches
      .open(CACHE_NAME)
      .then((cache) => cache.addAll(SHELL_ASSETS))
      .catch(() => {})
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key)))
      )
      .then(() => self.clients.claim())
  );
});

async function networkFirst(request, isApi) {
  const cache = await caches.open(CACHE_NAME);
  try {
    const response = await fetch(request);
    if (response && response.ok && response.type === 'basic') {
      cache.put(request, response.clone()).catch(() => {});
    }
    return response;
  } catch {
    const cached = await cache.match(request);
    if (cached) return cached;
    if (isApi) {
      return new Response(JSON.stringify({ error: 'offline' }), {
        status: 503,
        statusText: 'Service Unavailable',
        headers: { 'Content-Type': 'application/json; charset=utf-8' },
      });
    }
    return new Response('Offline — please check your internet connection.', {
      status: 503,
      statusText: 'Service Unavailable',
      headers: { 'Content-Type': 'text/plain; charset=utf-8' },
    });
  }
}

async function staleWhileRevalidate(request) {
  const cache = await caches.open(CACHE_NAME);
  const cached = await cache.match(request);
  const networkPromise = fetch(request)
    .then((response) => {
      if (response && response.ok && response.type === 'basic') {
        cache.put(request, response.clone()).catch(() => {});
      }
      return response;
    })
    .catch(() => null);

  if (cached) return cached;
  const fresh = await networkPromise;
  if (fresh) return fresh;
  return new Response('', { status: 504, statusText: 'Gateway Timeout' });
}

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname === '/sw.js') return;

  if (request.mode === 'navigate') {
    event.respondWith(networkFirst(request, false));
    return;
  }

  if (url.pathname.startsWith('/api/')) {
    event.respondWith(networkFirst(request, true));
    return;
  }

  if (isStaticShellAsset(url.pathname)) {
    event.respondWith(staleWhileRevalidate(request));
  }
});
