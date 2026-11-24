/**
 * Refresh the signed-in inbox/badge and reconcile read actions; notification access is rechecked by the server.
 * Maintainer map: docs/FRONTEND_GUIDE.md and docs/reference/FRONTEND.md.
 */
(() => {
  "use strict";
  const bell = document.querySelector("[data-notification-bell]");
  if (!bell) return;
  const badge = bell.querySelector("[data-notification-badge]");
  const feed = document.querySelector("[data-notice-feed]");
  let timer,
    busy = false,
    delay = 25000,
    stopped = false;
  const schedule = () => {
    clearTimeout(timer);
    if (!stopped) timer = setTimeout(refresh, delay);
  };
  async function refresh() {
    if (busy || stopped) return;
    if (document.hidden || !navigator.onLine) {
      schedule();
      return;
    }
    busy = true;
    try {
      const response = await fetch("/notifications/summary", {
        cache: "no-store",
        headers: { Accept: "application/json" },
        signal: AbortSignal.timeout(15000),
      });
      if (
        response.redirected ||
        response.status === 401 ||
        response.status === 403
      ) {
        stopped = true;
        badge.hidden = true;
        return;
      }
      if (!response.ok) throw new Error();
      const data = await response.json();
      badge.textContent = data.unread > 99 ? "99+" : String(data.unread);
      badge.hidden = !data.unread;
      bell.setAttribute(
        "aria-label",
        data.unread ? `Notifications, ${data.unread} unread` : "Notifications",
      );
      document.querySelectorAll("[data-notice-count]").forEach((node) => {
        node.textContent = data.unread;
      });
      if (feed && data.latest && data.latest !== feed.dataset.watermark) {
        feed.querySelector("[data-notice-refresh]").hidden = false;
      }
      delay = 25000;
    } catch (_) {
      delay = Math.min(delay * 2, 120000);
    } finally {
      busy = false;
      schedule();
    }
  }
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) refresh();
  });
  window.addEventListener("online", refresh);
  document.addEventListener("nurse:messages-read", refresh);
  schedule();
})();
