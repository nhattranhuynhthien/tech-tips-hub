// public/sw.js
// Service Worker for Tech Tips Hub:
// - Precaches core shell assets, /offline.html, and offline-accessible /vi/saved & /en/saved
// - Network-first for HTML navigations (with /offline.html fallback) and /api/*
// - Stale-while-revalidate for static shell assets
// - Caps dynamic cache entries (max 80) and tracks async cache writes via event.waitUntil()

const CACHE_NAME = 'techtips-hub-v2';
const MAX_DYNAMIC_ENTRIES = 80;
const SHELL_ASSETS = [
  '/manifest.webmanifest',
  '/favicon.svg',
  '/offline.html',
  '/vi/saved',
  '/en/saved',
  '/favicons/default.svg',
  '/icons/icon-192.png',
  '/js/actions.js',
  '/js/tip-card.js',
  '/js/search.js',
];

const SHELL_PATH_SET = new Set(SHELL_ASSETS);

function isStaticShellAsset(pathname) {
  return (
    pathname.startsWith('/_astro/') ||
    pathname.startsWith('/js/') ||
    pathname.startsWith('/favicons/') ||
    pathname.startsWith('/icons/') ||
    pathname === '/favicon.svg' ||
    pathname === '/manifest.webmanifest' ||
    pathname === '/offline.html' ||
    pathname === '/og-image.png'
  );
}

async function trimCache(cache, maxEntries) {
  try {
    const keys = await cache.keys();
    const dynamicKeys = keys.filter((req) => {
      try {
        return !SHELL_PATH_SET.has(new URL(req.url).pathname);
      } catch {
        return true;
      }
    });
    if (dynamicKeys.length <= maxEntries) return;
    const excess = dynamicKeys.slice(0, dynamicKeys.length - maxEntries);
    await Promise.all(excess.map((req) => cache.delete(req)));
  } catch {}
}

async function putWithCap(cache, request, response) {
  try {
    await cache.put(request, response);
    await trimCache(cache, MAX_DYNAMIC_ENTRIES);
  } catch {}
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

async function networkFirst(request, isApi, trackWrite) {
  const cache = await caches.open(CACHE_NAME);
  try {
    const response = await fetch(request);
    if (response && response.ok && response.type === 'basic') {
      trackWrite(putWithCap(cache, request, response.clone()));
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
    const offlinePage = await cache.match('/offline.html');
    if (offlinePage) return offlinePage;
    return new Response('Offline — please check your internet connection.', {
      status: 503,
      statusText: 'Service Unavailable',
      headers: { 'Content-Type': 'text/plain; charset=utf-8' },
    });
  }
}

async function staleWhileRevalidate(request, trackWrite) {
  const cache = await caches.open(CACHE_NAME);
  const cached = await cache.match(request);
  const networkPromise = fetch(request)
    .then((response) => {
      if (response && response.ok && response.type === 'basic') {
        trackWrite(putWithCap(cache, request, response.clone()));
      }
      return response;
    })
    .catch(() => null);

  if (cached) {
    trackWrite(networkPromise);
    return cached;
  }
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

  const trackWrite = (promise) => {
    if (typeof event.waitUntil === 'function') {
      event.waitUntil(promise);
    }
  };

  if (request.mode === 'navigate') {
    event.respondWith(networkFirst(request, false, trackWrite));
    return;
  }

  if (url.pathname.startsWith('/api/')) {
    event.respondWith(networkFirst(request, true, trackWrite));
    return;
  }

  if (isStaticShellAsset(url.pathname)) {
    event.respondWith(staleWhileRevalidate(request, trackWrite));
  }
});
