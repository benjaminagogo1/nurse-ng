(() => {
  "use strict";
  const panel = document.querySelector("[data-feedback-panel]");
  if (!panel) return;
  const close = panel.querySelector("[data-feedback-dismiss]");
  let lastForm;
  const focusPanel = () => {
    panel.focus({ preventScroll: true });
    const headerBottom =
      document.querySelector(".site-header")?.getBoundingClientRect().bottom ||
      0;
    const top =
      window.scrollY + panel.getBoundingClientRect().top - headerBottom - 16;
    window.scrollTo({ top: Math.max(0, top), behavior: "instant" });
  };
  const show = (notice) => {
    const tone = ["success", "info", "error"].includes(notice.tone)
      ? notice.tone
      : "error";
    panel.className = "action-feedback action-feedback--" + tone;
    panel.dataset.feedbackCompact = String(notice.compact === true);
    panel.setAttribute("role", tone === "error" ? "alert" : "status");
    panel.querySelector("#feedback-title").textContent = notice.title;
    panel.querySelector("#feedback-body").textContent = notice.body;
    panel.querySelectorAll("[data-feedback-icon]").forEach((icon) => {
      icon.hidden = icon.dataset.feedbackIcon !== tone;
    });
    panel.hidden = false;
    close.hidden = tone === "error";
    focusPanel();
  };
  document.addEventListener("nurse:feedback", (event) => {
    if (event.detail && typeof event.detail.body === "string")
      show(event.detail);
  });
  close?.addEventListener("click", () => {
    panel.hidden = true;
    const target =
      lastForm?.querySelector(
        'input:not([type="hidden"]), textarea, select, button',
      ) || document.getElementById("main");
    target?.focus({ preventScroll: true });
  });
  const descriptions = new WeakMap();
  const clearField = (field) => {
    field.removeAttribute("aria-invalid");
    if (descriptions.has(field)) {
      const original = descriptions.get(field);
      if (original) field.setAttribute("aria-describedby", original);
      else field.removeAttribute("aria-describedby");
      descriptions.delete(field);
    }
    document.getElementById(field.id + "-feedback")?.remove();
  };
  const markField = (field, text) => {
    if (!(field instanceof HTMLElement) || field.type === "hidden") return;
    clearField(field);
    if (!field.id)
      field.id = "account-field-" + Math.random().toString(36).slice(2);
    const hint = document.createElement("span");
    hint.id = field.id + "-feedback";
    hint.className = "field-feedback";
    hint.textContent = text;
    const original = field.getAttribute("aria-describedby") || "";
    descriptions.set(field, original);
    field.setAttribute(
      "aria-describedby",
      [original, hint.id].filter(Boolean).join(" "),
    );
    field.setAttribute("aria-invalid", "true");
    (field.closest(".input-affix") || field).after(hint);
  };
  const markFields = (form, fields = {}) => {
    Object.entries(fields).forEach(([name, text]) =>
      markField(form.elements.namedItem(name), text),
    );
  };
  // Controls named "action" can mask the form.action DOM property.
  const formAction = (form) =>
    new URL(form.getAttribute("action") || location.href, document.baseURI);
  const forms = [...document.querySelectorAll('form[method="post" i]')].filter(
    (form) =>
      !form.matches(
        ".message-compose, [data-reel-action], [data-reel-upload], [data-native-submit], [data-post-like]",
      ) && formAction(form).origin === location.origin,
  );
  const initialFields = document.querySelector("[data-feedback-fields]");
  if (initialFields) {
    try {
      forms.forEach((form) =>
        markFields(form, JSON.parse(initialFields.textContent)),
      );
    } catch {
      /* Text feedback remains available. */
    }
  }
  if (!panel.hidden) {
    close.hidden = panel.getAttribute("role") === "alert";
    focusPanel();
    // The browser may restore scroll position after deferred scripts run.
    window.addEventListener("pageshow", (event) => {
      if (event.persisted) panel.hidden = true;
      else if (!panel.hidden) focusPanel();
    });
  }
  if (!window.fetch || !window.AbortController) return;
  document.querySelectorAll("[data-native-submit]").forEach((form) => {
    const button = form.querySelector('[type="submit"]');
    const original = button ? [...button.childNodes] : [];
    const restore = () => {
      form.removeAttribute("aria-busy");
      if (button) {
        button.replaceChildren(...original);
        button.disabled = false;
      }
    };
    window.addEventListener("pageshow", restore);
    form.addEventListener("submit", (event) => {
      if (!navigator.onLine) {
        event.preventDefault();
        show({
          tone: "error",
          title: "You’re offline",
          body: "Reconnect to continue to your sign-in provider.",
        });
      } else if (form.hasAttribute("aria-busy")) {
        event.preventDefault();
      } else {
        form.setAttribute("aria-busy", "true");
        if (button) {
          button.textContent = "Connecting…";
          button.disabled = true;
        }
      }
    });
  });
  forms.forEach((form) => {
    form.dataset.feedbackForm = "";
    form.noValidate = true;
    let busy = false;
    let restoreButton = () => {};
    const live = document.createElement("p");
    live.className = "sr-only";
    live.setAttribute("role", "status");
    form.after(live);
    const unlock = () => {
      busy = false;
      form.removeAttribute("aria-busy");
      restoreButton();
      live.textContent = "";
    };
    window.addEventListener("pageshow", unlock);
    form.addEventListener("input", (event) => {
      if (event.target.matches("input, textarea, select")) {
        clearField(event.target);
        if (event.target.dataset.match) event.target.setCustomValidity("");
      }
    });
    // Run after composer listeners have written the current draft version into the form.
    document.addEventListener("submit", async (event) => {
      if (event.target !== form || event.defaultPrevented) return;
      event.preventDefault();
      if (busy) return;
      lastForm = form;
      form.querySelectorAll("[aria-invalid]").forEach(clearField);
      form.querySelectorAll("[data-match]").forEach((field) => {
        field.setCustomValidity(
          field.value === document.getElementById(field.dataset.match)?.value
            ? ""
            : "The passwords do not match. Enter the same password in both fields.",
        );
      });
      if (!form.checkValidity()) {
        const invalid = [...form.elements].filter(
          (field) => field.willValidate && !field.validity.valid,
        );
        invalid.forEach((field) => markField(field, field.validationMessage));
        show({
          tone: "error",
          title: "Check your details",
          body: "Please correct the highlighted fields and try again.",
        });
        return;
      }
      if (!navigator.onLine) {
        show({
          tone: "error",
          title: "You’re offline",
          body: "Reconnect to the internet, then try again. Your entries are still here.",
        });
        return;
      }
      const button =
        event.submitter ||
        form.querySelector('button:not([type]), [type="submit"]');
      form.dispatchEvent(new Event("nurse:submission-started"));
      const data = new FormData(form);
      if (button?.name) data.append(button.name, button.value);
      const original = button ? [...button.childNodes] : [];
      const label = form.dataset.pendingLabel || "Working…";
      busy = true;
      panel.hidden = true;
      form.setAttribute("aria-busy", "true");
      if (button) {
        const spinner = document.createElement("span");
        spinner.className = "feedback-spinner";
        spinner.setAttribute("aria-hidden", "true");
        button.replaceChildren(spinner, document.createTextNode(label));
        button.disabled = true;
        button.setAttribute("aria-disabled", "true");
        restoreButton = () => {
          button.replaceChildren(...original);
          button.disabled = false;
          button.removeAttribute("aria-disabled");
        };
      }
      live.textContent = label;
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 60000);
      let navigating = false;
      try {
        const response = await fetch(formAction(form).href, {
          method: "POST",
          body: data,
          credentials: "same-origin",
          signal: controller.signal,
          headers: { "X-Account-Feedback": "1", Accept: "application/json" },
        });
        if (
          response.redirected &&
          new URL(response.url).pathname === "/auth/login"
        ) {
          show({
            tone: "error",
            title: "Please sign in again",
            body: "Your session has ended. Your entries are still here. Sign in in another tab, then reload this page after keeping a copy of your work.",
          });
          return;
        }
        if (
          response.redirected &&
          response.ok &&
          new URL(response.url).origin === location.origin
        ) {
          navigating = true;
          window.location.assign(response.url);
          return;
        }
        let result = {};
        if (response.headers.get("content-type")?.includes("application/json"))
          result = await response.json();
        // Rejections have a known outcome; timeouts and server errors may have committed.
        if ([400, 401, 403, 404, 422, 429].includes(response.status)) {
          form.dispatchEvent(new Event("nurse:submission-rejected"));
        }
        if (response.ok && result.redirect) {
          const destination = new URL(result.redirect, location.origin);
          if (destination.origin !== location.origin)
            throw new Error("Unexpected destination");
          if (formAction(form).pathname === "/auth/logout") {
            document.dispatchEvent(new CustomEvent("nurse:signed-out"));
          }
          navigating = true;
          window.location.assign(destination.href);
          return;
        }
        if (result.feedback) {
          markFields(form, result.feedback.fields);
          show(result.feedback);
        } else if (response.status === 429) {
          const seconds = Number(response.headers.get("retry-after"));
          show({
            tone: "error",
            title: "Please wait before trying again",
            body:
              Number.isFinite(seconds) && seconds > 0
                ? "Too many attempts. Try again in " +
                  Math.ceil(seconds / 60) +
                  " minute(s). Your entries are still here."
                : "Too many attempts. Please try again shortly. Your entries are still here.",
          });
        } else if ([400, 401, 403].includes(response.status)) {
          show({
            tone: "error",
            title: "Please refresh this page",
            body: "Your session may have expired. Reload the page, sign in if needed, then try again.",
          });
        } else {
          show({
            tone: "error",
            title: "We couldn’t confirm the result",
            body: "Something interrupted this request. Check whether the action completed before trying again. Your entries are still here.",
          });
        }
      } catch {
        show({
          tone: "error",
          title: "We couldn’t confirm the result",
          body: "The connection was interrupted. Check whether the action completed before trying again. Your entries are still here.",
        });
      } finally {
        clearTimeout(timer);
        if (!navigating) unlock();
      }
    });
  });
})();
