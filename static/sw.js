const CACHE_NAME = 'budget-tracker-static-v3';
const ASSETS = ['/styles.css','/static/css/style.css','/static/css/improvements.css',
  '/static/js/main.js','/static/js/dashboard.js','/static/js/vendor/chart.min.js',
  '/static/manifest.json','/icons/icon-192.png','/icons/icon-512.png'];
self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE_NAME).then(cache => cache.addAll(ASSETS)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(
    keys.filter(key => key.startsWith('budget-tracker-') && key !== CACHE_NAME).map(key => caches.delete(key))
  )).then(() => self.clients.claim()));
});
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);
  if (event.request.method !== 'GET' || url.origin !== self.location.origin) return;
  if (ASSETS.includes(url.pathname)) {
    event.respondWith(caches.match(event.request).then(cached => cached || fetch(event.request)));
  } else if (event.request.mode === 'navigate') {
    event.respondWith(fetch(event.request).catch(() => new Response(
      '<!doctype html><html lang="en"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Offline — Budget Tracker</title><body style="font-family:system-ui;padding:40px;max-width:500px;margin:auto"><h1>You are offline</h1><p>Reconnect to view or change your budget securely.</p><button onclick="location.reload()">Try again</button></body></html>',
      { status:503, headers:{'Content-Type':'text/html','Cache-Control':'no-store'} }
    )));
  }
});
