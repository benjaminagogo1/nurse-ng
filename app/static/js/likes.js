/**
 * Submit explicit desired like state and reconcile counts from the server; repeated requests do not toggle.
 * Maintainer map: docs/FRONTEND_GUIDE.md and docs/reference/FRONTEND.md.
 */
(() => {
  "use strict";
  if (!window.fetch || !window.AbortController) return;
  document.addEventListener("submit", async (event) => {
    const form = event.target.closest("[data-post-like]");
    if (!form) return;
    event.preventDefault();
    if (form.dataset.busy) return;
    const related = [...document.querySelectorAll("[data-post-like]")].filter(
      (item) => item.dataset.postLike === form.dataset.postLike,
    );
    const buttons = related.map((item) => item.querySelector("button"));
    related.forEach((item) => { item.dataset.busy = "yes"; });
    buttons.forEach((button) => { button.disabled = true; });
    const status = form.querySelector("[data-like-status]");
    status.classList.add("sr-only");
    status.textContent = "Saving…";
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 12000);
    try {
      const response = await fetch(form.action, {
        method: "POST", body: new FormData(form), signal: controller.signal,
        headers: { "X-Post-Like": "1" },
      });
      if (response.redirected) throw new Error("Sign in again to like this video or post.");
      if (!response.ok) throw new Error("Could not save your like. Refresh the page and try again.");
      const result = await response.json();
      related.forEach((item) => {
        item.elements.liked.value = result.liked ? "no" : "yes";
        item.querySelector("button").setAttribute("aria-pressed", String(result.liked));
        item.querySelector("[data-like-label]").textContent = result.liked ? "Liked" : "Like";
        item.querySelector("[data-like-count]").textContent = String(result.likes);
      });
      status.textContent = result.liked ? "Liked." : "Like removed.";
    } catch (error) {
      status.classList.remove("sr-only");
      status.textContent = error.name === "AbortError" || error instanceof TypeError
        ? "Your like could not be confirmed. Reconnect and try again."
        : error.message;
    } finally {
      clearTimeout(timer);
      related.forEach((item) => { delete item.dataset.busy; });
      buttons.forEach((button) => { button.disabled = false; });
    }
  });
})();
