(() => {
  "use strict";
  const store = window.NurseOfflineStore;
  const shell = document.body.dataset.offlineShell === "true";
  const known = document.body.dataset.offlineSession === "known";
  const ready = (async () => {
    let scope = document.body.dataset.draftScope || "",
      authoritative = known;
    // Login/register HTML can omit the user even while the session is valid.
    // Only an authenticated session response can establish sign-out here.
    if (known && !scope) {
      try {
        const response = await fetchWithTimeout("/offline/session", {}, 5000);
        if (response.ok) scope = (await response.json()).scope;
        else if (![401, 403].includes(response.status)) authoritative = false;
      } catch {
        authoritative = false;
      }
    }
    return store.init(scope, authoritative);
  })();
  let network = navigator.onLine && !window.NurseNativeOffline ? "online" : "offline",
    failures = 0,
    checking = false,
    timer;
  let pending = 0,
    failed = 0,
    syncing = false;
  const labels = {
    online: "Online",
    offline: "Offline",
    poor: "Poor connection",
    syncing: "Syncing",
  };
  function paint() {
    for (const element of document.querySelectorAll("[data-connectivity]")) {
      element.textContent =
        (syncing ? "Syncing" : labels[network]) +
        (failed ? ` · ${failed} failed` : "") +
        (pending ? ` · ${pending} pending` : "");
      if (element.matches("a"))
        element.setAttribute(
          "aria-label",
          "Connection and offline changes: " + element.textContent,
        );
      element.dataset.state = syncing ? "syncing" : network;
    }
    for (const button of document.querySelectorAll("[data-offline-sync]")) {
      button.disabled = !store.available || network === "offline" || syncing;
      button.setAttribute("aria-busy", String(syncing));
      const label = button.querySelector("span");
      if (label)
        label.textContent = syncing
          ? "Syncing…"
          : network === "offline"
            ? "Reconnect to sync"
            : "Sync now";
    }
  }
  async function fetchWithTimeout(url, options = {}, timeout = 15000) {
    const controller = new AbortController(),
      started = performance.now();
    const timeoutId = setTimeout(() => controller.abort(), timeout);
    try {
      const result = await fetch(url, {
        ...options,
        cache: "no-store",
        signal: controller.signal,
      });
      network = performance.now() - started > 3000 ? "poor" : "online";
      failures = 0;
      paint();
      return result;
    } catch (error) {
      network = navigator.onLine ? "poor" : "offline";
      failures++;
      paint();
      throw error;
    } finally {
      clearTimeout(timeoutId);
    }
  }
  async function check() {
    clearTimeout(timer);
    if (checking) return;
    checking = true;
    if (!document.hidden && navigator.onLine) {
      try {
        await fetchWithTimeout("/offline/ping", {}, 5000);
        // The bundled shell has no server-rendered identity. Learn revocation
        // on reconnect even if this workspace only contains unsent drafts.
        if (shell && store.available) await window.NurseOffline.session?.();
      } catch {
        /* Quiet indicator. */
      }
    }
    checking = false;
    timer = setTimeout(
      check,
      Math.min(120000, 30000 * 2 ** Math.min(failures, 2)),
    );
  }
  window.addEventListener("online", () => {
    check();
    document.dispatchEvent(new Event("nurse:sync-request"));
  });
  window.addEventListener("offline", () => {
    network = "offline";
    paint();
  });
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) {
      check();
      document.dispatchEvent(new Event("nurse:sync-request"));
    }
  });
  navigator.serviceWorker?.addEventListener("message", (event) => {
    if (event.data?.type === "nurse:sync-ready")
      document.dispatchEvent(new Event("nurse:sync-request"));
  });
  window.NurseOffline = {
    store,
    ready,
    fetch: fetchWithTimeout,
    shell,
    setSyncState(count, errors, active) {
      pending = count;
      failed = errors;
      syncing = active;
      paint();
    },
    notice(body, tone = "info") {
      document.dispatchEvent(
        new CustomEvent("nurse:feedback", {
          detail: { title: "Offline & sync", body, tone },
        }),
      );
    },
  };
  ready.then((enabled) => {
    paint();
    const message = document.querySelector("[data-offline-intro]");
    if (message)
      message.textContent = enabled
        ? "Save your work here. Queued changes send when you reopen the app and reconnect."
        : `Sign in while connected to prepare this ${window.NurseNativeOffline ? "device" : "browser"} for offline use. Device storage must be available.`;
    if (store.error) window.NurseOffline.notice(store.error, "warning");
    document
      .querySelector("[data-offline-clear]")
      ?.addEventListener("click", async () => {
        try {
          await store.clear();
          location.reload();
        } catch {
          window.NurseOffline.notice(
            "Device storage could not be cleared. Check this browser’s storage settings.",
            "warning",
          );
        }
      });
    document.dispatchEvent(new Event("nurse:offline-ready"));
    if (shell && enabled) check();
  });
  if (!window.NurseNativeOffline && "serviceWorker" in navigator && window.isSecureContext) {
    navigator.serviceWorker.register("/service-worker.js").catch(() => {
      if (shell)
        window.NurseOffline.notice(
          "Offline navigation could not be prepared. Reconnect and try again.",
        );
    });
  }
  paint();
  check();
  window.addEventListener("pagehide", () => clearTimeout(timer));
})();
