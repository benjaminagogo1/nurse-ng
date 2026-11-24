/**
 * Load selected reply context without overwriting the composer; abort stale context requests.
 * Maintainer map: docs/FRONTEND_GUIDE.md and docs/reference/FRONTEND.md.
 */
// Keep a response's context visible without replacing text already in the composer.
(() => {
  "use strict";
  const form = document.querySelector("[data-reply-context-base]");
  if (!form) return;
  const target = form.elements.in_reply_to_id;
  const panel = form.querySelector("[data-reply-context]");
  const content = form.querySelector("[data-reply-context-content]");
  const body = form.elements.body;
  const base = form.dataset.replyContextBase;
  const postPath = base.replace(/\/reply-context\/$/, "");
  let request;
  const message = (text) => {
    const paragraph = document.createElement("p");
    paragraph.textContent = text;
    content.replaceChildren(paragraph);
  };
  const unavailable = () =>
    message(
      "The selected response is no longer available. Choose another response or reply to the conversation instead.",
    );
  const refresh = async () => {
    request?.abort();
    const selected = target.value;
    const locationURL = new URL(location.href);
    if (locationURL.searchParams.has("reply_to")) {
      locationURL.searchParams.set("reply_to", selected);
      if (locationURL.href !== location.href)
        history.replaceState(null, "", locationURL);
    }
    document.querySelectorAll(".reply-pagination a").forEach((link) => {
      const destination = new URL(link.href);
      if (selected || destination.searchParams.has("reply_to")) {
        destination.searchParams.set("reply_to", selected);
        link.href = destination;
      }
    });
    panel.hidden = !selected;
    if (!selected) {
      content.replaceChildren();
      return;
    }
    if (!/^[0-9a-f-]{36}$/i.test(selected)) {
      unavailable();
      return;
    }
    request = new AbortController();
    const current = request;
    message("Loading the response you’re answering…");
    try {
      const response = await fetch(base + encodeURIComponent(selected), {
        signal: current.signal,
        cache: "no-store",
        credentials: "same-origin",
      });
      if (current.signal.aborted || target.value !== selected) return;
      if (response.status === 404) {
        unavailable();
        return;
      }
      if (!response.ok) throw new Error("Context unavailable");
      const reference = await response.json();
      if (current.signal.aborted || target.value !== selected) return;
      if (
        reference.id !== selected ||
        typeof reference.author !== "string" ||
        typeof reference.excerpt !== "string"
      )
        throw new Error("Invalid context");
      const link = document.createElement("a");
      link.href = postPath + "/replies/" + encodeURIComponent(selected);
      link.textContent = "Replying to " + reference.author;
      const excerpt = document.createElement("p");
      excerpt.textContent = reference.excerpt;
      content.replaceChildren(link, excerpt);
    } catch (error) {
      if (error.name === "AbortError" || target.value !== selected) return;
      message(
        "Could not load this response. Your selection is kept; try again when your connection returns.",
      );
    }
  };
  const choose = (value) => {
    target.value = value;
    const url = new URL(postPath, location.origin);
    url.searchParams.set("page", form.elements.page.value);
    url.searchParams.set("reply_to", value);
    url.hash = "reply-form";
    history.replaceState(null, "", url);
    target.dispatchEvent(new Event("input", { bubbles: true }));
    refresh();
    body.focus({ preventScroll: true });
    document.getElementById("reply-form").scrollIntoView({ block: "start" });
  };
  document
    .querySelectorAll("[data-reply-to], [data-clear-reply-target]")
    .forEach((link) => {
      link.addEventListener("click", (event) => {
        if (
          event.button !== 0 ||
          event.ctrlKey ||
          event.metaKey ||
          event.shiftKey ||
          event.altKey ||
          target.disabled
        )
          return;
        event.preventDefault();
        choose(link.dataset.replyTo || "");
      });
    });
  form.addEventListener("community:reply-context", refresh);
  window.addEventListener("online", () => {
    if (target.value && !target.disabled) refresh();
  });
  refresh();
})();
