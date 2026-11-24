/**
 * Manage browser installation/help and browser-local reminder dismissal; native hosts hide the prompt.
 * Maintainer map: docs/FRONTEND_GUIDE.md and docs/reference/FRONTEND.md.
 */
(() => {
  "use strict";
  const native = window.Capacitor?.isNativePlatform?.() === true;
  const standalone = window.matchMedia("(display-mode: standalone)");
  const apple = /iPad|iPhone|iPod/.test(navigator.userAgent)
    || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  const platform = apple ? "apple" : /Android/.test(navigator.userAgent) ? "android" : "desktop";
  let deferredPrompt = null;
  let busy = false;
  let completed = false;
  let requested = false;
  let message = "";
  const reminderKey = "nurse-ng-install-reminder";
  function reminderHidden() {
    for (const storage of ["localStorage", "sessionStorage"]) {
      try {
        if (window[storage].getItem(reminderKey) === "hidden") return true;
      } catch { /* Installation still works when browser storage is unavailable. */ }
    }
    return false;
  }
  let dismissed = reminderHidden();
  function hideReminder() {
    dismissed = true;
    for (const storage of ["localStorage", "sessionStorage"]) {
      try {
        window[storage].setItem(reminderKey, "hidden");
        break;
      } catch { /* Keep the dismissal for this page if neither store is available. */ }
    }
  }
  const installed = () => native || completed || standalone.matches || navigator.standalone === true;
  const cards = document.querySelectorAll("[data-mobile-install]");
  const buttons = document.querySelectorAll("button[data-web-install]");
  const status = document.querySelector("[data-install-status]");
  const steps = document.querySelectorAll("[data-install-help]");

  function paint() {
    if (installed() && !dismissed) hideReminder();
    cards.forEach((card) => { card.hidden = dismissed || installed() || requested; });
    buttons.forEach((button) => {
      button.hidden = installed() || requested || (!deferredPrompt && !busy);
      button.disabled = busy;
    });
    steps.forEach((step) => { step.hidden = installed(); });
    if (!status) return;
    if (installed()) status.textContent = "You’re already using Nurse.ng as an app on this device.";
    else if (message) status.textContent = message;
    else if (!window.isSecureContext)
      status.textContent = "Open Nurse.ng using its secure HTTPS address to install it on this device.";
    else if (deferredPrompt)
      status.textContent = "Your browser is ready. Choose Install Nurse.ng, then confirm installation.";
    else if (apple)
      status.textContent = "Choose Install on iPhone below for the Add to Home Screen steps.";
    else if (platform === "android")
      status.textContent = "Choose Install on Android below, or use Install app in your browser’s menu.";
    else
      status.textContent = "Use the install icon or browser menu in Chrome or Edge. Steps are available below.";
  }

  function showSteps() {
    const step = document.querySelector(`[data-install-help="${platform}"]`);
    if (step) step.open = true;
  }

  async function install(event) {
    const trigger = event.currentTarget;
    if (trigger.dataset.installPlatform === "apple") return;
    if (trigger.dataset.installPlatform && trigger.dataset.installPlatform !== platform) return;
    if (installed() || requested) return;
    if (busy) {
      event.preventDefault();
      return;
    }
    // Links still open /app and device summaries still open their steps without a prompt.
    if (!deferredPrompt) {
      if (trigger.closest("[data-mobile-install]")) hideReminder();
      return;
    }
    event.preventDefault();
    const prompt = deferredPrompt;
    deferredPrompt = null;
    busy = true;
    message = "Confirm installation in your browser.";
    paint();
    try {
      // Invoke directly within the click's activation; a prompt can only be used once.
      await prompt.prompt();
      const choice = await prompt.userChoice;
      requested = choice.outcome === "accepted";
      hideReminder();
      message = requested
        ? "Installation started. Open Nurse.ng from your home screen or apps menu when it finishes."
        : "Installation was cancelled. You can still install from your browser’s menu using the steps below.";
      if (!requested) showSteps();
    } catch {
      message = "The browser couldn’t open installation. Follow the steps below to install from its menu.";
      showSteps();
    } finally {
      busy = false;
      paint();
    }
  }

  document.querySelectorAll("[data-web-install], [data-install-platform]").forEach((trigger) => {
    trigger.addEventListener("click", install);
  });
  document.querySelectorAll("[data-dismiss-install]").forEach((button) => {
    button.addEventListener("click", () => {
      hideReminder();
      paint();
      document.querySelector("#main")?.focus({ preventScroll: true });
    });
  });
  window.addEventListener("storage", (event) => {
    if (event.key !== reminderKey && event.key !== null) return;
    dismissed = reminderHidden();
    paint();
  });
  window.addEventListener("beforeinstallprompt", (event) => {
    if (installed() || requested || !window.isSecureContext) return;
    event.preventDefault();
    deferredPrompt = event;
    message = "";
    paint();
  });
  window.addEventListener("appinstalled", () => {
    completed = true;
    deferredPrompt = null;
    paint();
  });
  standalone.addEventListener("change", paint);
  paint();
})();
