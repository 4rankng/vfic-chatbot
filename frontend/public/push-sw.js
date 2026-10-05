/*
 * Web Push handlers for the console's service worker.
 *
 * Injected into the workbox-generated service worker by
 * `workbox.importScripts: ["push-sw.js"]` in vite.config.ts, so the generated
 * cache/fetch logic stays untouched. Payload contract (see
 * backend/app/services/push/service.py):
 *
 *   { title, body, url, tag }
 *
 * `tag` collapses repeats of the same alert (one stuck conversation, one OA)
 * into a single notification instead of a stack.
 */

const DEFAULT_TITLE = "TingTing";

const notificationOptions = (payload) => ({
  body: payload.body || "",
  tag: payload.tag || undefined,
  renotify: Boolean(payload.tag),
  data: { url: payload.url || "/" },
  icon: "./brand/tinghire-icon-192.png",
  badge: "./brand/tinghire-icon-192.png",
});

self.addEventListener("push", (event) => {
  let payload = {};
  try {
    payload = event.data ? event.data.json() : {};
  } catch {
    // A push that is not JSON still deserves a notification.
    payload = { body: event.data ? event.data.text() : "" };
  }
  event.waitUntil(
    self.registration.showNotification(payload.title || DEFAULT_TITLE, notificationOptions(payload)),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = (event.notification.data && event.notification.data.url) || "/";
  event.waitUntil(
    (async () => {
      const clientList = await self.clients.matchAll({
        type: "window",
        includeUncontrolled: true,
      });
      for (const client of clientList) {
        if ("focus" in client) {
          if ("navigate" in client) await client.navigate(target);
          return client.focus();
        }
      }
      return self.clients.openWindow(target);
    })(),
  );
});
