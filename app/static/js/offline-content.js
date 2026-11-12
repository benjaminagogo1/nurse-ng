/* Explicit drafts and deferred sending integrated with the existing forms. */
(() => {
  "use strict";
  const app = window.NurseOffline,
    store = app.store,
    TTL = 7 * 86400000;
  const host = document.querySelector("[data-offline-drafts]");
  const editor = document.querySelector("[data-offline-editor]");
  const liveForms = new Map(),
    snapshots = new WeakMap();
  const stale = () =>
    new Error(
      "This draft changed in another tab. Your typed text is still here. Open the latest draft in Offline & sync before saving or sending.",
    );
  const scriptsReady =
    document.readyState === "complete"
      ? Promise.resolve()
      : new Promise((resolve) => {
          document.addEventListener("DOMContentLoaded", resolve, {
            once: true,
          });
        });
  const fileDetails = (file) =>
    file
      ? { name: file.name, size: file.size, modified: file.lastModified }
      : null;
  const specs = {
    message: ["body", "client_key"],
    application: ["cover_note", "consent"],
    post: ["topic_id", "body", "community_name", "external_video_url"],
    reply: ["body", "community_name", "in_reply_to_id"],
    connection: [],
    reel: [
      "topic_id",
      "body",
      "category",
      "audience",
      "cover_seconds",
      "consent",
      "upload_key",
    ],
  };
  let repaintVersion = 0;
  function descriptor(form) {
    const path = new URL(form.action, location.href).pathname;
    let kind,
      target = {},
      title;
    if (/^\/messages\/[a-f0-9-]+$/.test(path)) {
      kind = "message";
      target.recipient_id = path.split("/")[2];
      title =
        "Message to " +
        (document.querySelector(".thread-header h2")?.textContent ||
          "your connection");
    } else if (/^\/jobs\/[a-f0-9-]+\/apply$/.test(path)) {
      kind = "application";
      target.job_id = path.split("/")[2];
      target.contact = JSON.parse(
        form.querySelector("[data-offline-contact]").textContent,
      );
      title =
        "Application: " +
        (document.querySelector("h1")?.textContent || "Saved opportunity");
    } else if (path === "/posts") {
      kind = "post";
      title = "Community conversation";
    } else if (/^\/posts\/[a-f0-9-]+\/replies$/.test(path)) {
      kind = "reply";
      target.post_id = path.split("/")[2];
      title = "Reply to a community conversation";
    } else if (path === "/reels" && form.matches("[data-reel-upload]")) {
      kind = "reel";
      title = "Reel draft";
    } else return null;
    const fields = specs[kind].map((name) => {
      const control = form.elements.namedItem(name);
      if (!control) return { name, type: "hidden", value: "" };
      return {
        name,
        type:
          control.tagName === "TEXTAREA"
            ? "textarea"
            : control.tagName === "SELECT"
              ? "select"
              : control.type,
        label:
          control.labels?.[0]?.textContent.trim() || name.replaceAll("_", " "),
        required: control.required,
        max: control.maxLength > 0 ? control.maxLength : 5000,
        options: control.options
          ? [...control.options].map((option) => [
              option.value,
              option.textContent,
            ])
          : undefined,
      };
    });
    return { id: kind + ":" + path, kind, title, path, target, fields };
  }
  function payloadFrom(form, draft) {
    const result = { ...draft.target };
    for (const name of specs[draft.kind]) {
      const control = form.elements.namedItem(name);
      result[name] =
        name === "consent" ? !!control?.checked : control?.value || "";
    }
    if (draft.kind === "reel")
      result.cover_seconds = Number(result.cover_seconds || 0);
    return result;
  }
  async function writable(draft, fence) {
    const current = await store.get("draft", draft.id);
    if ((current?.version || null) !== (draft.version || null)) throw stale();
    if (!current?.operation) return current;
    const op = await store.get("operation", current.operation);
    if (
      op &&
      !["failed", "conflict", "dismissed", "confirmed"].includes(op.status)
    ) {
      throw new Error(
        "This draft is awaiting server confirmation. Review it in Offline & sync.",
      );
    }
    if (op?.status === "confirmed")
      throw new Error(
        "This draft was just sent. Wait for its confirmation before starting another.",
      );
    if (op && ["failed", "conflict"].includes(op.status))
      await app.dismiss(op.id, fence);
    return current;
  }
  const save = (form, draft, notify = true) =>
    store.withLock("changes", (fence) => saveDraft(form, draft, notify, fence));
  async function saveDraft(form, draft, notify, fence) {
    if (!store.available)
      throw new Error("Reconnect and sign in to prepare offline drafts.");
    const expected = snapshots.has(form) ? snapshots.get(form) : draft;
    const previous = await writable(
      { id: draft.id, version: expected?.version },
      fence,
    );
    const value = {
      ...draft,
      payload: payloadFrom(form, draft),
      version: crypto.randomUUID(),
      operation: null,
    };
    if (
      draft.kind !== "reel" &&
      [...form.querySelectorAll("input[type=file]")].some(
        (input) => input.files?.length,
      )
    ) {
      throw new Error(
        "Offline community drafts support text and links. Attachments need a connected upload.",
      );
    }
    if (draft.kind === "reel") {
      const file = form.elements.video?.files?.[0];
      const captions = form.elements.captions?.files?.[0];
      if (captions?.size > 65536)
        throw new Error("Timed captions must be at most 64 KB.");
      value.captions = captions
        ? await captions.text()
        : previous?.captions || "";
      value.file = file ? await store.saveFile(file, fence) : previous?.file;
      value.fileName = file?.name || previous?.fileName || "";
      value.sourceFile = file ? fileDetails(file) : previous?.sourceFile;
      value.sourceCaptions = captions
        ? fileDetails(captions)
        : previous?.sourceCaptions;
    }
    // Ask the existing draft controller to freeze its exact version for acknowledgement.
    if (form.dataset.communityDraft) {
      form.dispatchEvent(new Event("nurse:offline-draft-saved"));
      value.community = {
        key: form.dataset.communityDraft,
        version: form.elements.draft_version.value,
      };
    }
    try {
      await store.put("draft", value.id, value, { ttl: TTL }, fence);
    } catch (error) {
      if (value.file && value.file !== previous?.file)
        await store.removeFile(value.file);
      throw error;
    }
    snapshots.set(form, value);
    if (previous?.file && previous.file !== value.file)
      await store.removeFile(previous.file, fence);
    if (notify)
      app.notice(
        "Draft saved locally in this browser. It has not been sent. Drafts are kept for up to 7 days.",
      );
    return value;
  }
  async function enqueue(draft) {
    if (draft.kind === "reel" && !draft.file)
      throw new Error("Choose and save an MP4 video before queuing this Reel.");
    if (["reel", "application"].includes(draft.kind) && !draft.payload.consent)
      throw new Error(
        "Review the details and consent before queuing this submission.",
      );
    const file = draft.file ? await store.get("file", draft.file) : null;
    if (draft.kind === "reel" && !file)
      throw new Error(
        "The saved video is unavailable. Save it again before publishing.",
      );
    const payload =
      draft.kind === "reel"
        ? {
            ...draft.payload,
            file_id: draft.file,
            file_size: file.size,
            captions: draft.captions,
          }
        : draft.payload;
    await app.queue(
      draft.kind,
      draft.id,
      draft.title,
      payload,
      {
        draft: { id: draft.id, version: draft.version },
        community: draft.community,
      },
      draft,
    );
  }
  function edit(draft) {
    if (!editor) return;
    const form = app.node("form", undefined, "stacked-form");
    form.dataset.offlineCompose = draft.kind;
    snapshots.set(form, draft);
    liveForms.set(draft.id, form);
    form.append(app.node("h2", draft.title));
    if (draft.kind === "application")
      form.append(
        app.node(
          "p",
          "Contact details shared: " +
            Object.values(draft.target.contact).filter(Boolean).join(" · "),
        ),
      );
    if (["post", "reply", "reel"].includes(draft.kind))
      form.append(
        app.node(
          "p",
          "This content will be public after successful publication. Keep patient information and private records out of it.",
        ),
      );
    for (const field of draft.fields) {
      let control = app.node(
        ["textarea", "select"].includes(field.type) ? field.type : "input",
      );
      control.name = field.name;
      control.id = "offline-compose-" + field.name;
      if (!["textarea", "select"].includes(field.type))
        control.type = field.type === "range" ? "number" : field.type;
      if (field.type === "select")
        for (const [value, label] of field.options || []) {
          const option = app.node("option", label);
          option.value = value;
          control.append(option);
        }
      if (field.type === "checkbox")
        control.checked = false; // Consent is reviewed on each new send.
      else control.value = draft.payload[field.name] ?? "";
      control.required = !!field.required;
      if (field.type !== "hidden") {
        const label = app.node("label", field.label);
        label.htmlFor = control.id;
        form.append(label);
      }
      if (field.max) control.maxLength = field.max;
      form.append(control);
    }
    if (draft.kind === "reel") {
      form.append(
        app.node(
          "p",
          draft.fileName
            ? "Saved video: " + draft.fileName
            : "Choose a video on Create a reel while connected.",
        ),
      );
    }
    let busy = false;
    const act = async (queued) => {
      if (busy) return;
      busy = true;
      const buttons = [...form.querySelectorAll("button")];
      buttons.forEach((button) => {
        button.disabled = true;
      });
      try {
        const saved = await save(form, draft, !queued);
        if (queued) await enqueue(saved);
        editor.hidden = true;
      } finally {
        busy = false;
        buttons.forEach((button) => {
          button.disabled = false;
        });
      }
    };
    form.append(app.button("Save draft locally", () => act(false)));
    const submit = app.node(
      "button",
      "Queue for synchronization",
      "btn btn-primary",
    );
    submit.type = "submit";
    form.append(submit);
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      try {
        await act(true);
      } catch (error) {
        app.notice(error.message, "warning");
      }
    });
    editor.replaceChildren(form);
    editor.hidden = false;
    editor.scrollIntoView();
    form.querySelector("textarea,input:not([type=hidden])")?.focus();
  }
  async function render() {
    if (!host) return;
    const generation = ++repaintVersion;
    if (!store.available) {
      app.count("drafts", null);
      host.replaceChildren(
        app.emptyState(
          "drafts",
          "Your drafts are private",
          "Sign in while connected to access your offline drafts.",
        ),
      );
      return;
    }
    const rows = await store.list("draft");
    if (generation !== repaintVersion || !store.available) return;
    app.count("drafts", rows.length);
    host.replaceChildren();
    for (const { value: draft } of rows) {
      const op = draft.operation
        ? await store.get("operation", draft.operation)
        : null;
      if (generation !== repaintVersion || !store.available) return;
      const waiting = op && ["pending", "syncing"].includes(op.status);
      const card = app.node("article", undefined, "offline-card");
      card.dataset.draftKind = draft.kind;
      card.append(
        app.node("h3", draft.title),
        app.node(
          "p",
          waiting ? "Waiting to sync" : "Draft · not sent",
          "offline-state",
        ),
        app.node(
          "p",
          (draft.payload.body || draft.payload.cover_note || "").slice(0, 300),
        ),
      );
      if (draft.fileName)
        card.append(app.node("p", draft.fileName, "offline-meta"));
      if (!waiting) {
        const actions = app.node("div", undefined, "offline-card-actions");
        actions.append(app.button("Open draft", () => edit(draft)));
        actions.append(
          app.button("Discard local draft", async () => {
            await store.withLock("changes", async (fence) => {
              await writable(draft, fence);
              if (draft.file) await app.discardUpload(draft.file);
              if (draft.file) await store.removeFile(draft.file, fence);
              await store.remove("draft", draft.id, fence);
            });
          }),
        );
        card.append(actions);
      }
      host.append(card);
    }
    if (!rows.length)
      host.append(
        app.emptyState(
          "drafts",
          "Room for your next idea",
          "Choose “Save draft locally” in a message, application, post or Reel. Your unfinished work will be right here.",
        ),
      );
  }
  async function reconcile(op) {
    if (op.metadata?.community)
      document.dispatchEvent(
        new CustomEvent("nurse:offline-published", {
          detail: op.metadata.community,
        }),
      );
    const ref = op.metadata?.draft;
    if (!ref || !store.available) return;
    await store.withLock("changes", async (fence) => {
      const current = await store.get("draft", ref.id);
      const form = liveForms.get(ref.id),
        snapshot = form && snapshots.get(form);
      // Another tab may have already removed the shared draft. Keep the editor's
      // saved snapshot until its own matching acknowledgement has been applied.
      const draft =
        snapshot?.version === ref.version
          ? snapshot
          : current?.version === ref.version
            ? current
            : null;
      if (!draft) return;
      const keyName = { message: "client_key", reel: "upload_key" }[draft.kind];
      if (
        form &&
        keyName &&
        form.elements[keyName]?.value === draft.payload[keyName]
      ) {
        if (form.elements.body.value === draft.payload.body)
          form.elements.body.value = "";
        form.elements[keyName].value = crypto.randomUUID();
        if (draft.kind === "reel") {
          form.elements.consent.checked = false;
          for (const [name, source] of [
            ["video", draft.sourceFile],
            ["captions", draft.sourceCaptions],
          ]) {
            const control = form.elements[name];
            if (
              control &&
              source &&
              JSON.stringify(fileDetails(control.files?.[0])) ===
                JSON.stringify(source)
            ) {
              control.value = "";
              control.dispatchEvent(new Event("change", { bubbles: true }));
            }
          }
        }
        form.dispatchEvent(new Event("nurse:offline-confirmed"));
      }
      if (snapshot?.version === ref.version) snapshots.set(form, null);
      if (current?.version === ref.version) {
        if (current.file) await store.removeFile(current.file, fence);
        await store.remove("draft", ref.id, fence);
      }
    });
  }
  async function forgetPublished(draft) {
    await store.withLock("changes", async (fence) => {
      const current = await store.get("draft", draft.id);
      if (current?.version !== draft.version) return;
      if (current.operation) {
        const op = await store.get("operation", current.operation);
        if (op && ["pending", "syncing"].includes(op.status)) return;
        if (op && ["failed", "conflict"].includes(op.status))
          await app.dismiss(op.id, fence);
      }
      if (current.file) await store.removeFile(current.file, fence);
      await store.remove("draft", current.id, fence);
      const form = liveForms.get(current.id);
      if (form && snapshots.get(form)?.version === current.version)
        snapshots.set(form, null);
    });
  }
  async function acknowledgeConnected(form, submitted) {
    if (!store.available) return;
    const spec = descriptor(form);
    if (!spec) return;
    const draft = await store.get("draft", spec.id);
    if (
      draft &&
      Object.entries(submitted).every(
        ([name, value]) => draft.payload[name] === value,
      )
    ) {
      await forgetPublished(draft);
    }
  }
  const repaint = () => render().catch(() => {});
  document.addEventListener("nurse:offline-change", repaint);
  document.addEventListener("nurse:operation-confirmed", (event) =>
    reconcile(event.detail).catch(() => {}),
  );
  app.ready
    .then(async (enabled) => {
      if (!enabled) {
        repaint();
        return;
      }
      // Connected draft controllers and their server acknowledgements must be ready first.
      await scriptsReady;
      const confirmation = document.getElementById("published-draft");
      if (confirmation) {
        const ref = JSON.parse(confirmation.textContent);
        for (const { value: draft } of await store.list("draft")) {
          if (
            draft.community?.key === ref.key &&
            draft.community.version === ref.version
          )
            await forgetPublished(draft);
        }
      }
      for (const row of await store.list("operation"))
        if (row.value.status === "confirmed") await reconcile(row.value);
      for (const form of document.querySelectorAll("form[method=post]")) {
        const draft = descriptor(form);
        if (!draft) continue;
        liveForms.set(draft.id, form);
        const controls = app.node("div", undefined, "offline-actions");
        let busy = false;
        const act = async (queued) => {
          if (busy) return;
          busy = true;
          form.dataset.offlineSaving = "true";
          const buttons = [...controls.querySelectorAll("button")];
          buttons.forEach((button) => {
            button.disabled = true;
          });
          try {
            if (queued && !form.reportValidity()) return;
            const saved = await save(form, draft, !queued);
            if (queued) await enqueue(saved);
          } finally {
            busy = false;
            form.dataset.offlineSaving = "false";
            buttons.forEach((button) => {
              button.disabled = false;
            });
          }
        };
        controls.append(
          app.button("Save draft locally", () => act(false)),
          app.button("Queue for synchronization", () => act(true)),
        );
        form.addEventListener(
          "submit",
          (event) => {
            if (
              form.dataset.offlinePending === "true" ||
              form.dataset.offlineSaving === "true"
            ) {
              event.preventDefault();
              event.stopImmediatePropagation();
              app.notice(
                "This form has a pending offline submission. Review Offline & sync before sending again.",
                "warning",
              );
            }
          },
          true,
        );
        const updatePending = async () => {
          if (!store.available) return;
          const saved = await store.get("draft", draft.id);
          const op = saved?.operation
            ? await store.get("operation", saved.operation)
            : null;
          form.dataset.offlinePending = String(
            !!op && ["pending", "syncing", "confirmed"].includes(op.status),
          );
        };
        document.addEventListener("nurse:offline-change", () =>
          updatePending().catch(() => {}),
        );
        await updatePending();
        await store.withLock("changes", async (fence) => {
          let prepared = await store.get("draft", draft.id);
          if (!prepared) {
            prepared = {
              ...draft,
              payload: payloadFrom(form, draft),
              version: crypto.randomUUID(),
            };
            // A prepared form has no publication intent. Never persist a prechecked consent.
            if ("consent" in prepared.payload) prepared.payload.consent = false;
            await store.put("draft", draft.id, prepared, { ttl: TTL }, fence);
          }
          snapshots.set(form, prepared);
        });
        form.append(controls);
      }
      repaint();
    })
    .catch(() => {});
  Object.assign(app, {
    saveDraft: save,
    queueDraft: enqueue,
    acknowledgeConnected,
  });
})();
