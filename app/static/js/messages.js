(() => {
  "use strict";
  const thread = document.querySelector("[data-conversation]");
  if (!thread) return;
  const base = thread.dataset.conversation;
  const list = thread.querySelector(".thread-messages");
  const form = thread.querySelector("form.message-compose");
  const body = form.elements.body,
    key = form.elements.client_key;
  const csrf = form.elements.csrf_token.value;
  const status = thread.querySelector(".thread-status");
  const older = thread.querySelector("[data-older]");
  const jump = thread.querySelector(".thread-new");
  const button = form.querySelector("button");
  const known = new Map(
    [...list.querySelectorAll("[data-message-id]")].map((node) => [
      node.dataset.messageId,
      node,
    ]),
  );
  let after = [...known.keys()].at(-1) || "",
    timer,
    busy = false,
    stopped = false;
  let delay = 4500,
    sending = false,
    lastBody = null,
    ackTimer,
    ackBusy = false;
  const receipts = new Set();
  function say(text, error = false) {
    status.textContent = text;
    status.classList.toggle("is-error", error);
  }
  const atBottom = () =>
    list.scrollHeight - list.scrollTop - list.clientHeight < 70;
  function bottom() {
    list.scrollTop = list.scrollHeight;
    jump.hidden = true;
  }
  function unavailable() {
    stopped = true;
    clearTimeout(timer);
    observer?.disconnect();
    list.replaceChildren();
    known.clear();
    receipts.clear();
    jump.hidden = true;
    body.value = "";
    body.disabled = true;
    button.disabled = true;
    say(
      "This conversation is no longer available. Check your connection or sign in again.",
      true,
    );
  }
  async function request(path, options = {}) {
    const response = await fetch(path, {
      cache: "no-store",
      ...options,
      headers: { Accept: "application/json", "X-Messages": "1" },
      signal: AbortSignal.timeout(15000),
    });
    if (response.redirected || [401, 403, 404].includes(response.status)) {
      unavailable();
      throw new Error("This conversation is no longer available.");
    }
    const data = await response.json();
    if (!response.ok)
      throw new Error(data.error || data.detail || "Please try again.");
    return data;
  }
  async function acknowledge() {
    if (
      stopped ||
      ackBusy ||
      document.hidden ||
      !navigator.onLine ||
      !receipts.size
    )
      return;
    ackBusy = true;
    const ids = [...receipts].slice(0, 100);
    const data = new FormData();
    data.set("csrf_token", csrf);
    data.set("ids", ids.join(","));
    try {
      await request(`${base}/read`, { method: "POST", body: data });
      ids.forEach((id) => receipts.delete(id));
      document.dispatchEvent(new Event("nurse:messages-read"));
    } catch (_) {
      /* Keep receipts for the next successful poll. */
    } finally {
      ackBusy = false;
    }
  }
  const observer =
    "IntersectionObserver" in window
      ? new IntersectionObserver(
          (entries) => {
            if (document.hidden || stopped) return;
            for (const entry of entries)
              if (entry.isIntersecting)
                receipts.add(entry.target.dataset.messageId);
            clearTimeout(ackTimer);
            ackTimer = setTimeout(acknowledge, 300);
          },
          { root: list, threshold: 0.1 },
        )
      : null;
  for (const node of known.values()) observer?.observe(node);
  function stamp(value) {
    return Date.parse(/(?:Z|[+-]\d\d:\d\d)$/.test(value) ? value : value + "Z");
  }
  function add(messages, history = false) {
    const pinned = atBottom(),
      height = list.scrollHeight,
      top = list.scrollTop;
    let count = 0;
    for (const message of messages) {
      if (known.has(message.id)) continue;
      const node = document.createElement("div");
      node.className = "message-bubble" + (message.mine ? " is-mine" : "");
      node.dataset.messageId = message.id;
      node.dataset.createdAt = message.created_at;
      const text = document.createElement("p");
      text.textContent = message.body;
      const time = document.createElement("time");
      time.dateTime = message.created_at;
      time.textContent = new Date(message.created_at).toLocaleString([], {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
      node.append(text, time);
      known.set(message.id, node);
      observer?.observe(node);
      count++;
    }
    if (count) {
      list.querySelector(".empty-state")?.remove();
      const sorted = [...known.values()].sort(
        (a, b) =>
          stamp(a.dataset.createdAt) - stamp(b.dataset.createdAt) ||
          a.dataset.messageId.localeCompare(b.dataset.messageId),
      );
      for (const node of sorted)
        list.insertBefore(node, list.querySelector("#latest"));
      if (history) list.scrollTop = top + list.scrollHeight - height;
      else if (pinned) bottom();
      else {
        list.scrollTop = top;
        jump.hidden = false;
      }
    }
    if (!observer && !document.hidden && atBottom()) {
      messages.forEach((message) => receipts.add(message.id));
      acknowledge();
    }
  }
  function schedule() {
    clearTimeout(timer);
    if (!stopped) timer = setTimeout(poll, delay);
  }
  async function poll() {
    if (busy || stopped) return;
    if (document.hidden || !navigator.onLine) {
      schedule();
      return;
    }
    busy = true;
    try {
      const data = await request(
        `${base}/updates${after ? "?after=" + encodeURIComponent(after) : ""}`,
      );
      if (stopped) return;
      add(data.messages);
      after = data.after || after;
      delay = data.more ? 300 : 4500;
      if (status.dataset.connectionError) {
        say("Connected. Your conversation is up to date.");
        delete status.dataset.connectionError;
      }
      await acknowledge();
    } catch (_) {
      if (!stopped) {
        say("Reconnecting… Your message stays here while we retry.", true);
        status.dataset.connectionError = "1";
      }
      delay = Math.min(delay * 2, 30000);
    } finally {
      busy = false;
      schedule();
    }
  }
  older.addEventListener("click", async (event) => {
    event.preventDefault();
    if (older.getAttribute("aria-busy") === "true" || stopped) return;
    older.setAttribute("aria-busy", "true");
    older.textContent = "Loading older messages…";
    try {
      const data = await request(
        `${base}/updates?before=${encodeURIComponent(older.dataset.older)}`,
      );
      if (stopped) return;
      add(data.messages, true);
      older.dataset.older = data.older || "";
      older.hidden = !data.older;
      older.href = `${base}?before=${data.older}`;
      say(
        data.older
          ? "Older messages loaded."
          : "You’ve reached the beginning of this conversation.",
      );
      if (older.hidden) list.focus({ preventScroll: true });
    } catch (error) {
      if (!stopped) say("Couldn’t load older messages. Try again.", true);
    } finally {
      older.removeAttribute("aria-busy");
      older.textContent = "Load older messages";
    }
  });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (sending || stopped || !body.value.trim()) return;
    const submitted = body.value;
    if (lastBody !== null && lastBody !== submitted)
      key.value = crypto.randomUUID();
    lastBody = submitted;
    const submittedKey = key.value;
    sending = true;
    button.disabled = true;
    say("Sending message…");
    try {
      const data = await request(base, {
        method: "POST",
        body: new FormData(form),
      });
      if (stopped) return;
      add([data.message]);
      bottom();
      if (body.value === submitted) body.value = "";
      key.value = crypto.randomUUID();
      lastBody = null;
      await window.NurseOffline?.acknowledgeConnected?.(form, {
        body: submitted,
        client_key: submittedKey,
      })?.catch(() => {});
      say("Message sent.");
      body.focus();
    } catch (error) {
      if (!stopped)
        say(
          `Message not confirmed. ${error.message || "Check your connection."} Your text is saved here; press Send to retry.`,
          true,
        );
    } finally {
      sending = false;
      button.disabled = stopped;
    }
  });
  form.addEventListener("nurse:offline-confirmed", () => {
    lastBody = null;
    say(
      body.value
        ? "Queued message sent. Your newer text stays here."
        : "Message sent.",
    );
    poll();
  });
  jump.addEventListener("click", bottom);
  list.addEventListener("scroll", () => {
    if (atBottom()) jump.hidden = true;
  });
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) {
      for (const node of known.values()) {
        observer?.unobserve(node);
        observer?.observe(node);
      }
      poll();
    }
  });
  window.addEventListener("online", poll);
  window.addEventListener("offline", () => {
    if (!stopped)
      say(
        "You’re offline. Your message stays here until you can send it.",
        true,
      );
  });
  if (!new URL(location.href).searchParams.has("before")) bottom();
  schedule();
})();
