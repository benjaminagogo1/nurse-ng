/**
 * Enhance staff charts and filters from authorized analytics responses; chart data stays staff-only.
 * Maintainer map: docs/FRONTEND_GUIDE.md and docs/reference/FRONTEND.md.
 */
/* Refresh staff analytics without generating member activity or losing selection. */
(() => {
  "use strict";
  const page = document.querySelector("[data-analytics-page]");
  if (!page) return;
  const content = page.querySelector("[data-analytics-content]");
  const button = page.querySelector("[data-analytics-refresh]");
  const label = page.querySelector("[data-live-label]");
  const live = page.querySelector("[data-analytics-live]");
  const status = page.querySelector("[data-refresh-status]");
  button.hidden = false;
  page.querySelector("[data-analytics-fallback]").hidden = true;
  let timer,
    busy = false,
    stopped = false;
  const schedule = () => {
    clearTimeout(timer);
    if (!stopped) timer = setTimeout(refresh, 30000);
  };
  function state(text, warning = false) {
    label.textContent = text;
    live.classList.toggle("is-stale", warning);
  }
  function usingContent() {
    const selected = window.getSelection();
    return (
      content.contains(document.activeElement) ||
      (selected &&
        !selected.isCollapsed &&
        content.contains(selected.anchorNode)) ||
      !!content.querySelector("details[open]")
    );
  }
  async function refresh(manual = false) {
    if (busy || stopped) return;
    if (document.hidden) {
      schedule();
      return;
    }
    if (!navigator.onLine) {
      state("Offline · showing last update", true);
      schedule();
      return;
    }
    if (!manual && usingContent()) {
      state("Updates paused while you explore");
      schedule();
      return;
    }
    busy = true;
    button.disabled = true;
    button.querySelector("span").textContent = "Refreshing…";
    const path = new URL("/staff/users/data", location.origin);
    path.search = location.search;
    try {
      const response = await fetch(path, {
        cache: "no-store",
        credentials: "same-origin",
        headers: { Accept: "text/html" },
        signal: AbortSignal.timeout(15000),
      });
      if (response.redirected || [401, 403].includes(response.status)) {
        stopped = true;
        content.replaceChildren();
        state("Access changed · reload to sign in", true);
        status.textContent =
          "Your staff session is no longer available. Reload this page to continue.";
        return;
      }
      if (!response.ok) throw new Error("refresh unavailable");
      const html = await response.text();
      // Interaction may begin during a slow response; defer replacing that view.
      if (document.hidden || (!manual && usingContent())) return;
      content.innerHTML = html;
      document.dispatchEvent(new Event("nurse:analytics-updated"));
      state("Updates every 30 seconds");
      if (manual) status.textContent = "Dashboard updated.";
    } catch (_) {
      state("Connection interrupted · showing last update", true);
      if (manual)
        status.textContent =
          "Could not refresh. The last available data is still shown.";
    } finally {
      busy = false;
      button.disabled = stopped;
      button.querySelector("span").textContent = "Refresh now";
      schedule();
    }
  }
  button.addEventListener("click", () => refresh(true));
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) refresh();
  });
  window.addEventListener("online", () => refresh());
  page.addEventListener("pointermove", showPoint);
  page.addEventListener("focus", showPoint, true);
  function showPoint(event) {
    const point = event.target.closest("[data-chart-point]");
    if (!point) return;
    page.querySelector("[data-chart-label]").textContent = point.dataset.date;
    page.querySelector("[data-chart-value]").textContent = point.dataset.count;
  }
  state("Updates every 30 seconds");
  schedule();
})();
