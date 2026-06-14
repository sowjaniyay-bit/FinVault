const CACHE = "finvault-v2";
const ASSETS = [
  "/frontend/home_app.html",
  "/frontend/dashboard.html",
  "/frontend/transactions.html",
  "/frontend/budget.html",
  "/frontend/insights.html",
  "/frontend/reports.html",
  "/frontend/goals.html",
  "/frontend/dues.html",
  "/frontend/ai_nudges.html",
  "/frontend/profile.html",
  "/frontend/about.html",
  "/frontend/login.html",
  "/frontend/signup.html",
  "/frontend/shared.css",
  "https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=Outfit:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap",
  "https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"
];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(ASSETS)).catch(()=>{}));
  self.skipWaiting();
});
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k=>k!==CACHE).map(k=>caches.delete(k)))));
  self.clients.claim();
});
self.addEventListener("fetch", e => {
  if(e.request.url.includes("127.0.0.1:5000")) return; // don't cache API

  // Network-first for HTML pages so scripts always re-execute on navigation
  if(e.request.destination === "document" || e.request.url.endsWith(".html")) {
    e.respondWith(
      fetch(e.request)
        .then(r => {
          const clone = r.clone();
          caches.open(CACHE).then(c => c.put(e.request, clone));
          return r;
        })
        .catch(() => caches.match(e.request).then(r => r || caches.match("/frontend/home_app.html")))
    );
    return;
  }

  // Cache-first for static assets (CSS, fonts, JS libs)
  e.respondWith(caches.match(e.request).then(r => r || fetch(e.request).catch(()=>{})));
});
