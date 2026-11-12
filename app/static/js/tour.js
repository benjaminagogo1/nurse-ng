/* Account-backed, cross-page walkthrough. The server owns steps and progress. */
(() => {
  "use strict";
  const config = document.getElementById("tour-config");
  const dialog = document.getElementById("guided-tour");
  if (!config || !dialog) return;
  if (typeof dialog.showModal !== "function") {
    document.querySelectorAll("[data-tour-unsupported]").forEach((el) => {
      el.hidden = false;
    });
    return;
  }
  let model;
  try {
    model = JSON.parse(config.textContent);
  } catch {
    return;
  }
  const csrf = model.csrf;
  const prompt = document.querySelector(".tour-prompt");
  const card = dialog.querySelector(".tour-card");
  const spotlight = dialog.querySelector(".tour-spotlight");
  const title = document.getElementById("tour-title");
  const copy = document.getElementById("tour-copy");
  const position = document.getElementById("tour-position");
  const progress = dialog.querySelector("progress");
  const next = dialog.querySelector("[data-tour-next]");
  const previous = dialog.querySelector('[data-tour-action="previous"]');
  const errorBox = dialog.querySelector(".tour-error");
  const note = dialog.querySelector("[data-tour-note]");
  let busy = false;
  let navigating = false;
  let epoch = 0;
  let target = null;
  let lastFocus = null;
  let observer = null;
  let resizeObserver = null;
  let frame = 0;
  let direction = "next";
  let needsSync = false;
  const current = () => model.steps[model.state.index];
  const active = () => model.state.status === "active" && !!current();
  const onPage = (step) =>
    [step.path, ...step.aliases].includes(location.pathname);
  const show = (root, selector, visible) => {
    root.querySelectorAll(selector).forEach((el) => {
      el.hidden = !visible;
    });
  };

  function controls() {
    const pending = busy || navigating;
    document.querySelectorAll("[data-tour-start]").forEach((button) => {
      if (!prompt.contains(button)) button.hidden = false;
      button.textContent = ["available", "offered"].includes(model.state.status)
        ? "Start tour"
        : "Restart tour";
    });
    document.querySelectorAll("[data-tour-resume]").forEach((button) => {
      if (!prompt.contains(button)) button.hidden = !active();
    });
    const settings = document.querySelector("[data-tour-settings-status]");
    if (settings) {
      const labels = {
        available: "Explore the essentials at your own pace.",
        offered: "Your tour is ready whenever you are.",
        active:
          "Your progress is saved. Resume where you left off, or start again.",
        completed:
          "Tour completed. You can take another look whenever you like.",
        skipped: "You skipped the tour. You can start again whenever you like.",
      };
      settings.textContent = labels[model.state.status];
    }
    previous.disabled = !active() || model.state.index === 0;
    document
      .querySelectorAll(
        "[data-tour-start], [data-tour-resume], [data-tour-action], [data-tour-next], [data-tour-sync]",
      )
      .forEach((button) =>
        button.setAttribute("aria-disabled", String(pending)),
      );
    card.setAttribute("aria-busy", String(pending));
    prompt.setAttribute("aria-busy", String(pending));
    dialog.querySelector("[data-tour-saving]").textContent = navigating
      ? "Opening the next section…"
      : busy
        ? "Saving tour progress…"
        : "";
  }

  function banner(message = "", finished = false) {
    controls();
    const offer = model.offer && model.state.status === "offered";
    prompt.hidden = dialog.open || !(active() || offer || message || finished);
    show(prompt, "[data-tour-start]", offer);
    show(prompt, "[data-tour-resume]", active());
    show(prompt, '[data-tour-action="skip"]', active() || offer);
    show(
      prompt,
      "[data-tour-settings], [data-tour-dismiss]",
      finished || !!message,
    );
    show(prompt, "[data-tour-prompt-error], [data-tour-sync]", false);
    const heading = prompt.querySelector("h2");
    heading.textContent = active()
      ? "Your tour is ready when you are"
      : "Get to know Nurse.ng";
    prompt.querySelector("[data-tour-prompt-copy]").textContent = active()
      ? "Continue with “" + current().title + "”. Your progress is saved."
      : "A short, guided look at the tools for your career. Explore at your own pace.";
    if (finished || message) {
      heading.textContent =
        model.state.status === "completed"
          ? "You’re ready to explore"
          : model.state.status === "skipped"
            ? "Tour skipped"
            : heading.textContent;
      prompt.querySelector("[data-tour-prompt-copy]").textContent =
        message ||
        "You can restart your guided tour any time in Account settings.";
    }
  }

  function clearMarker() {
    const url = new URL(location.href);
    ["tour", "tour_direction", "tour_notice"].forEach((key) =>
      url.searchParams.delete(key),
    );
    history.replaceState(history.state, "", url.href);
  }

  function cleanup() {
    observer?.disconnect();
    resizeObserver?.disconnect();
    observer = resizeObserver = null;
    cancelAnimationFrame(frame);
    frame = 0;
    target = null;
    if (dialog.open) dialog.close();
  }

  function pause() {
    epoch += 1; // An in-flight save may finish, but must not reopen or navigate.
    if (navigating) window.stop();
    navigating = false;
    cleanup();
    clearMarker();
    banner();
    const resume = prompt.querySelector("[data-tour-resume]");
    (lastFocus?.isConnected && !lastFocus.closest("[hidden]")
      ? lastFocus
      : resume
    ).focus();
  }

  function fail(message, expired = false) {
    needsSync = true;
    if (dialog.open) {
      errorBox.hidden = false;
      errorBox.querySelector("[data-tour-error]").textContent = message;
      show(errorBox, "[data-tour-login]", expired);
      show(errorBox, "[data-tour-sync]", !expired);
      place();
      errorBox.scrollIntoView({ block: "nearest", behavior: "instant" });
    } else {
      banner();
      prompt.hidden = false;
      const text = prompt.querySelector("[data-tour-prompt-error]");
      text.textContent = message;
      text.hidden = false;
      show(prompt, "[data-tour-sync]", true);
    }
  }

  async function request(action) {
    const abort = new AbortController();
    const timeout = setTimeout(() => abort.abort(), 12000);
    try {
      const body = new URLSearchParams({
        csrf_token: csrf,
        action: action || "",
        revision: String(model.state.revision),
        direction,
      });
      if (model.state.run_id) body.set("run_id", model.state.run_id);
      const response = await fetch("/tour", {
        method: action ? "POST" : "GET",
        credentials: "same-origin",
        cache: "no-store",
        headers: { Accept: "application/json" },
        body: action ? body : undefined,
        signal: abort.signal,
      });
      if (response.redirected || [401, 403].includes(response.status)) {
        throw Object.assign(
          new Error("Your session has changed. Sign in again to continue."),
          {
            expired: true,
          },
        );
      }
      if (
        !(response.headers.get("content-type") || "").includes(
          "application/json",
        )
      ) {
        throw new Error(
          "Your progress could not be checked. Please try again.",
        );
      }
      const result = await response.json();
      if (
        response.status === 400 &&
        result.detail === "Invalid or missing CSRF token."
      ) {
        throw Object.assign(
          new Error("Your session has changed. Sign in again to continue."),
          {
            expired: true,
          },
        );
      }
      if (response.status === 409) {
        model = result;
        throw new Error(result.message);
      }
      if (!response.ok)
        throw new Error(
          result.message ||
            "Your progress could not be saved. Please try again.",
        );
      model = result;
      needsSync = false;
      return result;
    } finally {
      clearTimeout(timeout);
    }
  }

  async function mutate(action) {
    if (busy || navigating) return;
    // After an uncertain response, first read the saved position. Never replay
    // an action automatically: it may already have committed on the server.
    if (needsSync) {
      await resume();
      return;
    }
    const operation = epoch;
    busy = true;
    controls();
    errorBox.hidden = true;
    try {
      const result = await request(action);
      if (operation !== epoch) {
        banner();
        return;
      }
      busy = false;
      controls();
      if (active()) {
        direction =
          action === "previous"
            ? "previous"
            : action === "unavailable"
              ? direction
              : "next";
        await go(result.message);
      } else {
        cleanup();
        clearMarker();
        banner(result.message, true);
        prompt.querySelector("h2").focus();
      }
    } catch (error) {
      if (operation === epoch) {
        fail(
          error.name === "AbortError"
            ? "The connection took too long. Check your saved progress before continuing."
            : error instanceof TypeError
              ? "We couldn’t save your progress. Check your connection, then check your saved progress."
              : error.message || "Check your connection and try again.",
          error.expired,
        );
      }
    } finally {
      busy = false;
      controls();
    }
  }

  async function resume() {
    if (busy || navigating) return;
    const operation = epoch;
    busy = true;
    controls();
    try {
      await request();
      if (operation !== epoch) {
        banner();
        return;
      }
      busy = false;
      errorBox.hidden = true;
      if (active()) await go();
      else {
        cleanup();
        clearMarker();
        banner(
          "Your saved tour is up to date. You can start again in Account settings.",
          true,
        );
        prompt.querySelector("h2").focus();
      }
    } catch (error) {
      if (operation === epoch)
        fail(
          "We couldn’t check your tour. Check your connection, or sign in again if your session ended.",
          error.expired,
        );
    } finally {
      busy = false;
      controls();
    }
  }

  function visible(element) {
    if (!element?.isConnected || !element.getClientRects().length) return false;
    if (element.closest('[hidden], [aria-hidden="true"]')) return false;
    if (element.checkVisibility) {
      return element.checkVisibility({
        checkOpacity: true,
        checkVisibilityCSS: true,
      });
    }
    const style = getComputedStyle(element);
    return style.visibility !== "hidden" && style.opacity !== "0";
  }

  async function findTarget(step, operation) {
    const end = performance.now() + 1400;
    do {
      if (operation !== epoch) return null;
      const element = document.querySelector(step.target);
      if (visible(element)) return element;
      await new Promise((resolve) => setTimeout(resolve, 80));
    } while (performance.now() < end);
    return null;
  }

  function place() {
    if (!dialog.open || !target) return;
    const view = window.visualViewport;
    const bounds = {
      left: (view?.offsetLeft || 0) + 12,
      top: (view?.offsetTop || 0) + 12,
      width: (view?.width || innerWidth) - 24,
      height: (view?.height || innerHeight) - 24,
    };
    const right = bounds.left + bounds.width;
    const bottom = bounds.top + bounds.height;
    card.style.maxWidth = bounds.width + "px";
    card.style.maxHeight = bounds.height + "px";
    let rect = target.getBoundingClientRect();
    const headerBottom =
      document.querySelector(".site-header")?.getBoundingClientRect().bottom ||
      0;
    const safeTop = Math.max(bounds.top, headerBottom + 12);
    if (rect.top < safeTop && window.scrollY > 0) {
      window.scrollBy({ top: rect.top - safeTop, behavior: "instant" });
      rect = target.getBoundingClientRect();
    }
    const left = Math.max(bounds.left - 4, rect.left - 7);
    const top = Math.max(bounds.top - 4, rect.top - 7);
    const width = Math.max(0, Math.min(right + 4, rect.right + 7) - left);
    const height = Math.max(0, Math.min(bottom + 4, rect.bottom + 7) - top);
    Object.assign(spotlight.style, {
      left: left + "px",
      top: top + "px",
      width: width + "px",
      height: height + "px",
    });
    let box = card.getBoundingClientRect();
    const gap = 20;
    // In a short landscape viewport, use a narrower side position before
    // covering the target. The copy scrolls while navigation stays available.
    if (
      top + height + gap + box.height > bottom &&
      top - box.height - gap < bounds.top
    ) {
      const sideSpace = Math.max(
        left - gap - bounds.left,
        right - left - width - gap,
      );
      if (sideSpace >= 260 && sideSpace < box.width) {
        card.style.maxWidth = sideSpace + "px";
        box = card.getBoundingClientRect();
      }
    }
    const middle = left + (width - box.width) / 2;
    const sideTop = Math.max(bounds.top, Math.min(bottom - box.height, top));
    const candidates = [
      { x: middle, y: top + height + gap },
      { x: middle, y: top - box.height - gap },
      { x: left + width + gap, y: sideTop },
      { x: left - box.width - gap, y: sideTop },
    ];
    const fits = (point) =>
      point.x >= bounds.left &&
      point.x + box.width <= right &&
      point.y >= bounds.top &&
      point.y + box.height <= bottom;
    // Clamp horizontal alignment for full-width targets before testing vertical space.
    candidates.slice(0, 2).forEach((point) => {
      point.x = Math.max(bounds.left, Math.min(right - box.width, point.x));
    });
    const selected = candidates.find(fits) || {
      // When an enlarged target and tooltip cannot fit together, expose as
      // much of the target as possible along the opposite edge.
      x:
        bounds.width >= 600
          ? left + width / 2 < bounds.left + bounds.width / 2
            ? right - box.width
            : bounds.left
          : bounds.left + (bounds.width - box.width) / 2,
      y: bottom - box.height,
    };
    card.style.left = Math.max(bounds.left, selected.x) + "px";
    card.style.top = Math.max(bounds.top, selected.y) + "px";
  }

  function schedulePlace() {
    if (frame || !dialog.open) return;
    frame = requestAnimationFrame(() => {
      frame = 0;
      if (!visible(target)) {
        cleanup();
        void mutate("unavailable");
      } else place();
    });
  }

  async function go(message = "") {
    if (!active()) return;
    const step = current();
    const url = new URL(
      onPage(step) ? location.href : step.path,
      location.origin,
    );
    url.searchParams.set("tour", model.state.run_id);
    url.searchParams.set("tour_direction", direction);
    if (message) url.searchParams.set("tour_notice", "unavailable");
    else url.searchParams.delete("tour_notice");
    if (!onPage(step)) {
      navigating = true;
      controls();
      location.assign(url.href);
      return;
    }
    if (document.querySelector("dialog[open]:not(#guided-tour)")) {
      banner("Close the open panel, then resume your tour.");
      return;
    }
    history.replaceState(history.state, "", url.href);
    cleanup();
    prompt.hidden = true;
    const operation = ++epoch;
    const element = await findTarget(step, operation);
    if (operation !== epoch) return;
    if (!element) {
      await mutate("unavailable");
      return;
    }
    target = element;
    target.scrollIntoView({
      block: "start",
      inline: "nearest",
      behavior: "instant",
    });
    // The site already has document scroll padding. Align explicitly so it
    // does not combine with a target's margin and waste mobile spotlight space.
    const headerBottom =
      document.querySelector(".site-header")?.getBoundingClientRect().bottom ||
      0;
    window.scrollBy({
      top: target.getBoundingClientRect().top - Math.max(20, headerBottom + 20),
      behavior: "instant",
    });
    title.textContent = step.title;
    copy.textContent = step.body;
    dialog.querySelector(".tour-content").scrollTop = 0;
    position.textContent =
      "Step " + (model.state.index + 1) + " of " + model.steps.length;
    progress.max = model.steps.length;
    progress.value = model.state.index + 1;
    next.textContent =
      model.state.index === model.steps.length - 1 ? "Finish" : "Next →";
    note.textContent = message;
    note.hidden = !message;
    errorBox.hidden = true;
    dialog.dataset.step = step.key;
    dialog.showModal();
    place();
    controls();
    title.focus({ preventScroll: true });
    observer = new MutationObserver(schedulePlace);
    observer.observe(document.getElementById("main"), {
      subtree: true,
      childList: true,
      attributes: true,
      attributeFilter: ["hidden", "style", "class", "aria-hidden"],
    });
    resizeObserver = new ResizeObserver(schedulePlace);
    resizeObserver.observe(target);
    resizeObserver.observe(card);
  }

  document.querySelectorAll("[data-tour-start]").forEach((button) => {
    button.addEventListener("click", () => {
      lastFocus = button;
      direction = "next";
      void mutate("start");
    });
  });
  document
    .querySelectorAll("[data-tour-resume], [data-tour-sync]")
    .forEach((button) => {
      button.addEventListener("click", () => {
        lastFocus = button;
        void resume();
      });
    });
  document.querySelectorAll("[data-tour-action]").forEach((button) => {
    button.addEventListener("click", () => {
      void mutate(button.dataset.tourAction);
    });
  });
  next.addEventListener("click", () => {
    void mutate(
      model.state.index === model.steps.length - 1 ? "finish" : "next",
    );
  });
  dialog.querySelector("[data-tour-pause]").addEventListener("click", pause);
  dialog.addEventListener("cancel", (event) => {
    event.preventDefault();
    pause();
  });
  dialog.addEventListener("keydown", (event) => {
    if (event.key === "Tab") {
      const buttons = [
        ...dialog.querySelectorAll("button:not(:disabled), a[href]"),
      ].filter(
        (element) =>
          !element.closest("[hidden]") && element.getClientRects().length,
      );
      const first = buttons[0];
      const last = buttons[buttons.length - 1];
      if (
        event.shiftKey &&
        (document.activeElement === first || document.activeElement === title)
      ) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus();
      }
      return;
    }
    if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey)
      return;
    if (event.key === "ArrowRight") {
      event.preventDefault();
      next.click();
    }
    if (event.key === "ArrowLeft" && !previous.disabled) {
      event.preventDefault();
      previous.click();
    }
  });
  prompt.querySelector("[data-tour-dismiss]").addEventListener("click", () => {
    prompt.hidden = true;
    document.getElementById("main").focus({ preventScroll: true });
  });
  window.addEventListener("resize", schedulePlace);
  window.addEventListener("scroll", schedulePlace, { passive: true });
  window.visualViewport?.addEventListener("resize", schedulePlace);
  window.visualViewport?.addEventListener("scroll", schedulePlace);
  // Pages restored from browser history must consult the account, not a stale DOM.
  window.addEventListener("pageshow", (event) => {
    if (!event.persisted) return;
    epoch += 1;
    cleanup();
    clearMarker();
    navigating = false;
    busy = false;
    request()
      .then(() => banner())
      .catch(() => banner("Resume your tour to check saved progress."));
  });

  banner();
  const params = new URLSearchParams(location.search);
  if (
    active() &&
    params.get("tour") === model.state.run_id &&
    onPage(current())
  ) {
    direction =
      params.get("tour_direction") === "previous" ? "previous" : "next";
    void go(
      params.get("tour_notice") === "unavailable"
        ? "An unavailable section was passed over. Let’s continue here."
        : "",
    );
  } else if (params.has("tour")) clearMarker();
})();
