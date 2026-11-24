/**
 * Apply browser-local theme/text/contrast/motion preferences before CSS loads to prevent theme flash.
 * Maintainer map: docs/FRONTEND_GUIDE.md and docs/reference/FRONTEND.md.
 */
// Run before stylesheets so a saved dark theme is applied before first paint.
(() => {
  "use strict";
  const storageKey = "nurse-ng-display";
  const defaults = {
    theme: "system",
    largeText: false,
    highContrast: false,
    reduceMotion: false,
  };
  const systemDark = matchMedia("(prefers-color-scheme: dark)");
  const systemMotion = matchMedia("(prefers-reduced-motion: reduce)");
  const root = document.documentElement;
  const normalize = (value) => ({
    theme: ["system", "light", "dark"].includes(value?.theme)
      ? value.theme
      : "system",
    largeText: value?.largeText === true,
    highContrast: value?.highContrast === true,
    reduceMotion: value?.reduceMotion === true,
  });
  const read = () => {
    try {
      return normalize(JSON.parse(localStorage.getItem(storageKey)));
    } catch {
      return { ...defaults };
    }
  };
  let preferences = read();
  const apply = () => {
    const dark =
      preferences.theme === "dark" ||
      (preferences.theme === "system" && systemDark.matches);
    root.dataset.theme = dark ? "dark" : "light";
    root.dataset.textSize = preferences.largeText ? "large" : "default";
    root.dataset.contrast = preferences.highContrast ? "high" : "default";
    root.dataset.motion =
      preferences.reduceMotion || systemMotion.matches ? "reduce" : "default";
    document
      .querySelector('meta[name="theme-color"]')
      ?.setAttribute("content", dark ? "#101a24" : "#073c40");
  };
  apply();
  systemDark.addEventListener("change", apply);
  systemMotion.addEventListener("change", apply);

  document.addEventListener("DOMContentLoaded", () => {
    const dialog = document.getElementById("display-preferences");
    const form = document.getElementById("display-form");
    if (!dialog?.showModal || !form) return;
    const sync = () => {
      form.elements.theme.value = preferences.theme;
      ["largeText", "highContrast", "reduceMotion"].forEach((key) => {
        form.elements[key].checked = preferences[key];
      });
    };
    const save = () => {
      apply();
      sync();
      const status = document.getElementById("display-save-status");
      try {
        localStorage.setItem(storageKey, JSON.stringify(preferences));
        status.textContent = "Preferences saved in this browser.";
      } catch {
        status.textContent =
          "Preferences applied for this page. Browser storage is unavailable.";
      }
    };
    sync();
    let returnFocusTo = null;
    document.querySelectorAll("[data-display-open]").forEach((button) => {
      button.hidden = false;
      button.addEventListener("click", () => {
        document.querySelectorAll(".header-popover[open]").forEach((menu) => {
          menu.open = false;
        });
        const navigation = document.getElementById("mobile-navigation");
        const fromNavigation = navigation?.open && navigation.contains(button);
        returnFocusTo = fromNavigation
          ? document.querySelector(".nav-toggle")
          : button;
        if (fromNavigation) navigation.close();
        if (!dialog.open) dialog.showModal();
      });
    });
    dialog.addEventListener("close", () => {
      if (returnFocusTo?.isConnected && returnFocusTo.getClientRects().length)
        returnFocusTo.focus();
      returnFocusTo = null;
    });
    dialog.querySelectorAll("[data-display-close]").forEach((button) => {
      button.addEventListener("click", () => dialog.close());
    });
    dialog.addEventListener("click", (event) => {
      if (event.target !== dialog) return;
      const bounds = dialog.getBoundingClientRect();
      if (
        event.clientX < bounds.left ||
        event.clientX > bounds.right ||
        event.clientY < bounds.top ||
        event.clientY > bounds.bottom
      )
        dialog.close();
    });
    form.addEventListener("submit", (event) => event.preventDefault());
    form.addEventListener("change", () => {
      preferences = normalize({
        theme: form.elements.theme.value,
        largeText: form.elements.largeText.checked,
        highContrast: form.elements.highContrast.checked,
        reduceMotion: form.elements.reduceMotion.checked,
      });
      save();
    });
    form.querySelector("[data-display-reset]").addEventListener("click", () => {
      preferences = { ...defaults };
      save();
    });
    window.addEventListener("storage", (event) => {
      if (event.key !== storageKey && event.key !== null) return;
      preferences = read();
      apply();
      sync();
    });
  });
})();
