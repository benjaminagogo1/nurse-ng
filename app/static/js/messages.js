/**
 * Render authorized private conversation updates, reply context and attachment upload/send progress.
 * Maintainer map: docs/FRONTEND_GUIDE.md and docs/reference/FRONTEND.md.
 */
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
  const picker = form.elements.files;
  const selectedList = form.querySelector(".message-selected-files");
  const selected = [];
  const limits = {
    count: Number(form.dataset.fileCount),
    each: Number(form.dataset.fileMax),
    total: Number(form.dataset.fileTotal),
  };
  const extensions = new Set("jpg jpeg png webp gif mp3 wav m4a aac ogg opus flac mp4 m4v mov webm pdf docx xlsx pptx odt ods odp rtf txt csv".split(" "));
  let pending = null, activeUpload = null;
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
    const pinned = atBottom();
    status.textContent = text;
    status.classList.toggle("is-error", error);
    if (pinned) bottom();
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
    stopMedia(true);
    activeUpload?.abort();
    clearSelected();
    pending = null;
    list.replaceChildren();
    known.clear();
    receipts.clear();
    jump.hidden = true;
    body.value = "";
    body.disabled = true;
    button.disabled = true;
    picker.disabled = true;
    say(
      "This conversation is no longer available. Check your connection or sign in again.",
      true,
    );
  }
  function stopMedia(discard = false) {
    for (const media of list.querySelectorAll("audio, video")) {
      media.pause();
      if (discard) {
        media.removeAttribute("src");
        media.querySelectorAll("source").forEach((source) => source.removeAttribute("src"));
        media.load();
      }
    }
  }
  function clearSelected() {
    selected.forEach((item) => item.preview && URL.revokeObjectURL(item.preview));
    selected.length = 0;
    picker.value = "";
    selectedList.replaceChildren();
    form.dataset.messageFiles = "0";
    form.elements.attachment_ids.value = "";
  }
  function showSelected() {
    selectedList.replaceChildren();
    form.dataset.messageFiles = String(selected.length);
    form.elements.attachment_ids.value = selected.filter((item) => item.id).map((item) => item.id).join(",");
    picker.disabled = stopped || sending || !!pending;
    for (const item of selected) {
      const row = document.createElement("li");
      if (item.preview) {
        const preview = document.createElement("img");
        preview.src = item.preview;
        preview.alt = "";
        row.append(preview);
      }
      const copy = document.createElement("span");
      const name = document.createElement("strong");
      name.textContent = item.file.name;
      const detail = document.createElement("small");
      detail.textContent = item.id ? "Ready to send" : `${(item.file.size / (1024 * 1024)).toFixed(1)} MB`;
      item.detail = detail;
      copy.append(name, detail);
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "message-file-remove";
      remove.textContent = "×";
      remove.setAttribute("aria-label", `Remove ${item.file.name}`);
      remove.disabled = sending || !!pending;
      remove.addEventListener("click", () => {
        if (sending || pending) return;
        if (item.preview) URL.revokeObjectURL(item.preview);
        selected.splice(selected.indexOf(item), 1);
        showSelected();
        if (item.id) {
          const data = new FormData();
          data.set("csrf_token", csrf);
          request(`/messages/attachments/${item.id}/discard`, {method: "POST", body: data}).catch(() => {});
        }
      });
      row.append(copy, remove);
      selectedList.append(row);
    }
  }
  picker.addEventListener("change", () => {
    if (sending || stopped || pending) { picker.value = ""; return; }
    for (const file of picker.files) {
      if (!extensions.has(file.name.split(".").at(-1).toLowerCase())) {
        say("Choose an image, audio/video file, PDF, modern Office document or text file.", true);
        continue;
      }
      if (!file.size || file.size > limits.each) {
        say(`Each file must be between 1 byte and ${limits.each / (1024 * 1024)} MB.`, true);
        continue;
      }
      if (selected.length >= limits.count || selected.reduce((sum, item) => sum + item.file.size, file.size) > limits.total) {
        say(`Choose up to ${limits.count} files, ${limits.total / (1024 * 1024)} MB in total.`, true);
        break;
      }
      selected.push({file, uploadKey: crypto.randomUUID(), preview: file.type.startsWith("image/") ? URL.createObjectURL(file) : null});
    }
    picker.value = "";
    showSelected();
    if (atBottom()) bottom();
  });
  function upload(item, index) {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      activeUpload = xhr;
      xhr.open("POST", `${base}/attachments`);
      xhr.setRequestHeader("Accept", "application/json");
      xhr.setRequestHeader("X-Messages", "1");
      xhr.timeout = 180000;
      const data = new FormData();
      data.set("csrf_token", csrf);
      data.set("upload_key", item.uploadKey);
      data.set("file", item.file, item.file.name);
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable) {
          const percent = Math.min(100, Math.round(event.loaded / event.total * 100));
          item.detail.textContent = percent === 100 ? "Checking file…" : `Uploading ${percent}%`;
          if (percent === 100) say(`Checking file ${index + 1} of ${selected.length}…`);
        }
      };
      xhr.onload = () => {
        activeUpload = null;
        if ([401,403,404].includes(xhr.status) || new URL(xhr.responseURL).pathname !== `${base}/attachments`) {
          unavailable();
          reject(new Error("This conversation is no longer available."));
          return;
        }
        try {
          const result = JSON.parse(xhr.responseText);
          if (xhr.status < 200 || xhr.status >= 300) throw new Error(result.error || result.detail || "File upload failed.");
          if (!result.attachment?.id) throw new Error("File upload was not confirmed.");
          item.id = result.attachment.id;
          item.detail.textContent = "Ready to send";
          resolve();
        } catch (error) { reject(error); }
      };
      xhr.onerror = xhr.ontimeout = xhr.onabort = () => {
        activeUpload = null;
        reject(new Error("The file upload was not confirmed. Check your connection and retry."));
      };
      say(`Uploading file ${index + 1} of ${selected.length}…`);
      xhr.send(data);
    });
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
    if (!response.ok) {
      const error = new Error(data.error || data.detail || "Please try again.");
      error.status = response.status;
      throw error;
    }
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
      if (message.body) {
        const text = document.createElement("p");
        text.textContent = message.body;
        node.append(text);
      }
      if (message.attachments?.length) node.append(fileCards(message.attachments));
      const time = document.createElement("time");
      time.dateTime = message.created_at;
      time.textContent = window.NurseTime.format(message.created_at);
      node.append(time);
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
  function fileCards(files) {
    const container = document.createElement("div");
    container.className = "message-files";
    for (const file of files) {
      // File paths are opaque server IDs; never turn member-supplied text into HTML.
      if (!/^[0-9a-f-]{36}$/.test(file.id)) continue;
      const url = `/messages/files/${file.id}`;
      const card = document.createElement("div");
      card.className = "message-file-card";
      if (file.kind === "image") {
        const link = document.createElement("a");
        link.href = url; link.target = "_blank"; link.rel = "noopener";
        const img = document.createElement("img");
        img.src = url; img.alt = file.name; img.loading = "lazy";
        img.className = "message-file-image";
        link.append(img); card.append(link);
      } else if (["audio", "video"].includes(file.kind)) {
        const media = document.createElement(file.kind);
        media.controls = true; media.preload = "none";
        media.setAttribute("aria-label", file.name);
        if (file.kind === "video") media.playsInline = true;
        const source = document.createElement("source");
        source.src = url; source.type = file.content_type;
        media.append(source); card.append(media);
      }
      const meta = document.createElement("div"); meta.className = "message-file-meta";
      const copy = document.createElement("span"); copy.className = "message-file-copy";
      const name = document.createElement("strong"); name.textContent = file.name;
      const detail = document.createElement("small");
      detail.textContent = `${file.kind[0].toUpperCase() + file.kind.slice(1)} · ${file.size_label}`;
      copy.append(name, detail);
      const download = document.createElement("a");
      download.className = "message-file-download"; download.href = url + "?download=1";
      download.textContent = "Download"; download.setAttribute("aria-label", `Download ${file.name}`);
      meta.append(copy, download); card.append(meta); container.append(card);
    }
    return container;
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
    if (sending || stopped || (!pending && !body.value.trim() && !selected.length)) return;
    if (!navigator.onLine) {
      say("You’re offline. Your text and selected files stay here; reconnect to send.", true);
      return;
    }
    const submitted = pending ? pending.body : body.value;
    if (!pending && lastBody !== null && lastBody !== submitted)
      key.value = crypto.randomUUID();
    lastBody = submitted;
    const submittedKey = pending ? pending.key : key.value;
    sending = true;
    button.disabled = true;
    showSelected();
    try {
      for (let i = 0; i < selected.length; i++) {
        if (!selected[i].id) await upload(selected[i], i);
        if (stopped) return;
      }
      const ids = pending ? pending.ids : selected.map((item) => item.id);
      const payload = new FormData();
      payload.set("csrf_token", csrf);
      payload.set("body", submitted);
      payload.set("client_key", submittedKey);
      payload.set("attachment_ids", ids.join(","));
      // Keep the exact file payload until confirmation, even if a newer caption is typed.
      if (ids.length) pending = {body: submitted, key: submittedKey, ids};
      say("Sending message…");
      const data = await request(base, {
        method: "POST",
        body: payload,
      });
      if (stopped) return;
      add([data.message]);
      bottom();
      if (body.value === submitted) body.value = "";
      resizeComposer();
      key.value = crypto.randomUUID();
      lastBody = null;
      pending = null;
      clearSelected();
      await window.NurseOffline?.acknowledgeConnected?.(form, {
        body: submitted,
        client_key: submittedKey,
      })?.catch(() => {});
      say("Message sent.");
      body.focus();
    } catch (error) {
      if ([400, 413, 422, 429].includes(error.status)) pending = null;
      if (!stopped)
        say(
          `Message not confirmed. ${error.message || "Check your connection."} Your text${selected.length ? " and files stay" : " stays"} here; press Send to retry${pending ? " the original message" : ""}.`,
          true,
        );
    } finally {
      sending = false;
      button.disabled = stopped;
      showSelected();
    }
  });
  form.addEventListener("nurse:offline-confirmed", () => {
    lastBody = null;
    resizeComposer();
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
  window.addEventListener("pagehide", () => {
    clearTimeout(timer);
    activeUpload?.abort();
    stopMedia();
    selected.forEach((item) => {
      if (item.preview) URL.revokeObjectURL(item.preview);
      item.preview = null;
    });
  });
  window.addEventListener("pageshow", (event) => {
    if (!event.persisted || stopped) return;
    for (const item of selected) {
      if (item.file.type.startsWith("image/")) item.preview = URL.createObjectURL(item.file);
    }
    showSelected();
    poll();
  });
  function resizeComposer() {
    body.style.height = "auto";
    body.style.height = Math.min(body.scrollHeight, 124) + "px";
  }
  body.addEventListener("input", () => {
    const pinned = atBottom();
    resizeComposer();
    if (pinned) bottom();
  });
  resizeComposer();
  if (!new URL(location.href).searchParams.has("before")) bottom();
  schedule();
})();
