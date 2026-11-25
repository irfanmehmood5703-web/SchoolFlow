// Bump when the public opening screen or its assets change. Workspace pages are never cached.
const openingCache = 'schoolflow-opening-v1';
const openingPage = '/opening/screen.html';
const openingFiles = [openingPage, '/opening/start.css', '/opening/start.js'];
let readyUntil = 0;

self.addEventListener('install', event => {
  event.waitUntil((async () => {
    const cache = await caches.open(openingCache);
    await cache.addAll(openingFiles);
    await self.skipWaiting();
  })());
});

self.addEventListener('activate', event => {
  event.waitUntil((async () => {
    for (const key of await caches.keys()) {
      if (key.startsWith('schoolflow-opening-') && key !== openingCache) await caches.delete(key);
    }
    await self.clients.claim();
  })());
});

self.addEventListener('message', event => {
  if (event.origin === self.location.origin && event.data === 'schoolflow-backend-ready') {
    readyUntil = Date.now() + 20_000;
  }
});

self.addEventListener('fetch', event => {
  const request = event.request;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (openingFiles.includes(url.pathname)) {
    event.respondWith(caches.open(openingCache).then(cache => cache.match(url.pathname))
      .then(saved => saved || fetch(request)));
    return;
  }

  if (request.mode === 'navigate' && openable(url)) {
    event.respondWith(openOrWait(request));
  }
});

function openable(url) {
  return url.pathname === '/' || url.pathname === '/workspace/dashboard'
    || url.pathname === '/auth/institute' || url.pathname === '/auth/login'
    || url.pathname === '/vendor/login';
}

async function openOrWait(request) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), Date.now() < readyUntil ? 20_000 : 2_000);
  let response;
  try {
    response = await fetch(request, { signal: controller.signal });
    if (response.type === 'opaqueredirect' || response.headers.get('X-SchoolFlow-Response') === '1') {
      return response;
    }
  } catch (error) {
    // A slow or unavailable host uses the locally saved public opening page.
  } finally {
    clearTimeout(timer);
  }

  const cache = await caches.open(openingCache);
  return await cache.match(openingPage) || response || Response.error();
}
