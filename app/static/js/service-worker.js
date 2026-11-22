/* Only public application assets and the neutral shell belong in this cache. */
"use strict";
const CACHE = "nurse-offline-shell-v41";
const ASSETS = [
  "/offline-shell",
  "/static/css/app.css?v=7",
  "/static/css/design.css?v=12",
  "/static/css/appearance.css?v=11",
  "/static/css/feedback.css?v=4",
  "/static/css/engagement.css?v=1",
  "/static/css/community-growth.css?v=4",
  "/static/css/participation.css?v=2",
  "/static/css/notifications.css?v=8",
  "/static/css/messages.css?v=3",
  "/static/css/opportunities.css",
  "/static/css/discovery.css?v=8",
  "/static/css/offline.css?v=12",
  "/static/css/profile.css?v=2",
  "/static/css/jobs.css?v=2",
  "/static/css/mobile-app.css?v=6",
  "/static/js/mobile-app.js?v=3",
  "/static/js/display.js?v=2",
  "/static/js/time-display.js?v=1",
  "/static/js/app.js?v=2",
  "/static/js/feedback.js?v=10",
  "/static/js/likes.js?v=1",
  "/static/js/community-replies.js",
  "/static/js/community-growth.js?v=1",
  "/static/js/community-drafts.js?v=3",
  "/static/js/offline-store.js?v=6",
  "/static/js/offline.js?v=11",
  "/static/js/offline-sync.js?v=6",
  "/static/js/offline-data.js?v=12",
  "/static/js/offline-content.js?v=13",
  "/static/img/favicon.svg",
  "/static/img/app-icon-180.png",
  "/static/img/app-icon-192.png",
  "/static/img/app-icon-512.png",
  "/static/js/offline-upload.js?v=6",
];
self.addEventListener("install", (event) =>
  event.waitUntil(
    (async () => {
      const cache = await caches.open(CACHE);
      await cache.addAll(
        ASSETS.map(
          (url) => new Request(url, { credentials: "omit", cache: "reload" }),
        ),
      );
      await self.skipWaiting();
    })(),
  ),
);
self.addEventListener("activate", (event) =>
  event.waitUntil(
    (async () => {
      for (const name of await caches.keys()) {
        if (name.startsWith("nurse-offline-shell-") && name !== CACHE)
          await caches.delete(name);
      }
      await self.clients.claim();
    })(),
  ),
);
self.addEventListener("fetch", (event) => {
  const request = event.request,
    url = new URL(request.url);
  if (request.method !== "GET" || url.origin !== self.location.origin) return;
  if (request.mode === "navigate") {
    event.respondWith(
      (async () => {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), 8000);
        // Adding fetch options resets navigation metadata to same-origin/empty.
        // Preserve top-level navigation intent for the tour and activity tracking.
        const headers = new Headers(request.headers);
        if (request.destination === "document")
          headers.set("X-Nurse-Navigation", "document");
        else headers.delete("X-Nurse-Navigation");
        try {
          return await fetch(request, { headers, signal: controller.signal });
        } catch {
          return (await caches.match("/offline-shell")) || Response.error();
        } finally {
          clearTimeout(timer);
        }
      })(),
    );
  } else if (ASSETS.includes(url.pathname + url.search)) {
    event.respondWith(
      (async () => (await caches.match(request)) || fetch(request))(),
    );
  }
});
self.addEventListener("sync", (event) => {
  if (event.tag !== "nurse-offline-sync") return;
  event.waitUntil(
    (async () => {
      for (const client of await self.clients.matchAll({ type: "window" }))
        client.postMessage({ type: "nurse:sync-ready" });
    })(),
  );
});
