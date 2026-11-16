// Community text stays in this tab; only session-change signals are shared between tabs.
(() => {
  "use strict";
  const prefix = "nurse-ng-draft:v1:";
  const controlPrefix = "nurse-ng-draft-control:v1:";
  const activeKey = controlPrefix + "active";
  const scope = document.body.dataset.draftScope || "";
  const expiry = 24 * 60 * 60 * 1000;
  const forms = [...document.querySelectorAll("[data-community-draft]")];
  const controllers = [];
  let storage;
  let shared;
  let enabled = true;
  let ended = false;
  let channel;
  try {
    channel = new BroadcastChannel("nurse-ng-community-drafts");
  } catch {
    /* Optional. */
  }
  const send = (message) => channel?.postMessage({ ...message, scope });
  const eachDraft = (callback) => {
    for (let i = storage.length - 1; i >= 0; i--) {
      const key = storage.key(i);
      if (key?.startsWith(prefix)) callback(key);
    }
  };
  const clearTab = () => eachDraft((key) => storage.removeItem(key));
  const revokedKey = (owner) => controlPrefix + "revoked:" + owner;
  const revoke = (owner) => {
    if (!owner) return;
    shared.setItem(revokedKey(owner), "1");
    channel?.postMessage({ type: "logout", scope: owner });
  };
  const currentSession = () =>
    enabled &&
    scope &&
    !shared.getItem(revokedKey(scope)) &&
    shared.getItem(activeKey) === scope;
  const stop = (clear, message) => {
    enabled = false;
    if (clear) {
      try {
        clearTab();
      } catch {
        /* Storage may have been disabled. */
      }
    }
    controllers.forEach((controller) => controller.stop(clear, message));
  };
  const unavailable = () =>
    stop(
      false,
      "Draft recovery is unavailable in this browser. Keep a copy before leaving.",
    );
  const signedOut = () => {
    ended = true;
    stop(
      true,
      "Draft cleared because this sign-in session ended. Sign in again to continue.",
    );
  };
  try {
    storage = window.sessionStorage;
    shared = window.localStorage;
    // Require both stores so an old tab cannot restore drafts after another tab signs out.
    const probe = controlPrefix + "probe";
    storage.setItem(probe, "1");
    storage.removeItem(probe);
    shared.setItem(probe, "1");
    shared.removeItem(probe);
    if (scope && shared.getItem(revokedKey(scope))) {
      enabled = false;
      ended = true;
      clearTab();
    } else {
      const previous = shared.getItem(activeKey);
      if (previous !== scope) {
        revoke(previous);
        shared.setItem(activeKey, scope);
      }
      eachDraft((key) => {
        if (!scope || !key.startsWith(prefix + scope + ":"))
          storage.removeItem(key);
      });
    }
  } catch {
    enabled = false;
  }

  const storageKey = (composer) => prefix + scope + ":" + composer;
  const read = (key) => {
    const raw = storage.getItem(key);
    if (!raw) return null;
    try {
      const record = JSON.parse(raw);
      if (
        record.scope !== scope ||
        typeof record.version !== "string" ||
        !/^[a-f0-9-]{36}$/.test(record.version) ||
        !Number.isFinite(record.savedAt) ||
        record.savedAt > Date.now() ||
        Date.now() - record.savedAt > expiry ||
        !record.fields ||
        Object.values(record.fields).some(
          (value) => typeof value !== "string" || value.length > 10000,
        )
      ) {
        throw new Error("Invalid or expired draft");
      }
      return record;
    } catch {
      storage.removeItem(key);
      return null;
    }
  };
  const acknowledge = (confirmation) => {
    if (
      !confirmation ||
      typeof confirmation.key !== "string" ||
      typeof confirmation.version !== "string"
    )
      return;
    const key = storageKey(confirmation.key);
    const record = read(key);
    if (record?.version === confirmation.version) {
      storage.removeItem(key);
      storage.setItem(key + ":cleared", confirmation.version);
      controllers.forEach((controller) => controller.published(confirmation));
    }
  };
  document.addEventListener("nurse:offline-published", (event) => {
    if (!enabled) return;
    acknowledge(event.detail);
    send({ type: "published", confirmation: event.detail });
  });
  if (enabled && scope) {
    try {
      eachDraft((key) => {
        if (!key.endsWith(":cleared")) read(key);
      });
      const confirmation = document.getElementById("published-draft");
      if (confirmation) {
        const data = JSON.parse(confirmation.textContent);
        acknowledge(data);
        send({ type: "published", confirmation: data });
      }
    } catch {
      unavailable();
    }
  }

  forms.forEach((form) => {
    const composer = form.dataset.communityDraft;
    const key = storageKey(composer);
    const controls = form.querySelector("[data-draft-controls]");
    const status = form.querySelector("[data-draft-status]");
    const discard = form.querySelector("[data-discard-draft]");
    const version = form.elements.draft_version;
    const fields = [
      "body",
      "topic_id",
      "external_video_url",
      "community_name",
      "in_reply_to_id",
      "post_kind",
      "title",
      "activity_format",
      "activity_starts_at",
    ]
      .map((name) => form.elements.namedItem(name))
      .filter(Boolean);
    const defaults = Object.fromEntries(
      fields.map((field) => [field.name, field.value]),
    );
    let rememberedVersion = "";
    const say = (message) => {
      if (status.textContent !== message) status.textContent = message;
    };
    const snapshot = () =>
      Object.fromEntries(fields.map((field) => [field.name, field.value]));
    const hasText = (values) =>
      fields.some((field) =>
        ["topic_id", "post_kind", "activity_format"].includes(field.name)
          ? values[field.name] !== defaults[field.name]
          : values[field.name].trim(),
      );
    const clearForm = () => {
      fields.forEach((field) => {
        field.value = ["topic_id", "post_kind"].includes(field.name) ? defaults[field.name] : "";
      });
      form.querySelectorAll('input[type="file"]').forEach((field) => {
        field.value = "";
      });
      version.value = "";
      rememberedVersion = "";
      discard.hidden = true;
      form.dispatchEvent(new Event("community:reply-context"));
    };
    const save = (pending = false, knownFailure = false) => {
      if (!enabled) return;
      try {
        if (!currentSession()) {
          signedOut();
          return;
        }
        const values = snapshot();
        const hadFiles = [...form.querySelectorAll('input[type="file"]')].some(
          (field) => field.files.length,
        );
        if (!hasText(values) && !hadFiles) {
          storage.removeItem(key);
          version.value = "";
          rememberedVersion = "";
          discard.hidden = true;
          say("No draft saved.");
          return;
        }
        const existing = read(key);
        const sameText =
          existing &&
          JSON.stringify(existing.fields) === JSON.stringify(values);
        const token = sameText ? existing.version : crypto.randomUUID();
        storage.setItem(
          key,
          JSON.stringify({
            scope,
            version: token,
            fields: values,
            savedAt: Date.now(),
            hadFiles,
            pending: pending || (!knownFailure && sameText && existing.pending),
          }),
        );
        storage.removeItem(key + ":cleared");
        version.value = token;
        rememberedVersion = token;
        discard.hidden = false;
        say(
          pending
            ? "Submitting… Your draft stays until publication is confirmed."
            : "Draft saved in this tab.",
        );
      } catch {
        unavailable();
      }
    };
    const restore = () => {
      const record = read(key);
      if (!record) return false;
      fields.forEach((field) => {
        if (
          field.name === "in_reply_to_id" &&
          form.dataset.replyTargetExplicit === "true"
        )
          return;
        const value =
          record.fields[field.name] ??
          (field.name === "in_reply_to_id" ? "" : undefined);
        if (typeof value !== "string") return;
        if (
          field.tagName === "SELECT" &&
          ![...field.options].some((option) => option.value === value)
        ) {
          field.value = "";
        } else field.value = value;
      });
      if (form.elements.external_video_url?.value) {
        form.querySelector(".conversation-attachments").open = true;
      }
      version.value = record.version;
      rememberedVersion = record.version;
      discard.hidden = false;
      say(
        record.pending
          ? "Draft restored after a submission attempt. Check the conversation before sending again."
          : "Draft restored in this tab.",
      );
      if (
        form.elements.in_reply_to_id &&
        (record.fields.in_reply_to_id || "") !==
          form.elements.in_reply_to_id.value
      )
        save();
      form.dataset.replyTargetExplicit = "false";
      form.dispatchEvent(new Event("community:reply-context"));
      return true;
    };
    controls.hidden = false;
    controllers.push({
      stop(clear, message) {
        if (clear) {
          clearForm();
          fields.forEach((field) => {
            field.disabled = true;
          });
          form.querySelector('button[type="submit"]').disabled = true;
        }
        say(message);
      },
      published(confirmation) {
        if (
          confirmation.key === composer &&
          confirmation.version === rememberedVersion
        ) {
          clearForm();
          say("Published. Draft cleared.");
        }
      },
      resume() {
        if (
          !restore() &&
          (rememberedVersion || storage.getItem(key + ":cleared"))
        ) {
          clearForm();
          say("No draft saved.");
        }
      },
    });
    if (ended) {
      signedOut();
    } else if (!enabled) {
      say(
        "Draft recovery is unavailable in this browser. Keep a copy before leaving.",
      );
    } else {
      try {
        if (!currentSession()) {
          signedOut();
          return;
        }
        // The server's validation response is authoritative; never overwrite it with older text.
        if (form.dataset.draftError === "true") save(false, true);
        else if (!restore()) {
          if (form.elements.in_reply_to_id?.value) save();
          else say("Your text will be saved in this tab as you type.");
        }
      } catch {
        unavailable();
      }
    }
    form.addEventListener("input", () => save());
    form.addEventListener("change", () => save());
    form.addEventListener("submit", (event) => {
      // Enhanced forms announce when validation passes and a request actually starts.
      if (enabled) save(!form.hasAttribute("data-feedback-form"));
      // Activity-only fields are intentionally disabled on ordinary conversations.
      if (ended) event.preventDefault();
    });
    form.addEventListener("nurse:submission-started", () => save(true));
    form.addEventListener("nurse:offline-draft-saved", () => save());
    form.addEventListener("nurse:submission-rejected", () => save(false, true));
    discard.addEventListener("click", () => {
      try {
        storage?.removeItem(key);
        storage?.setItem(key + ":cleared", "discarded");
      } catch {
        /* The text can still be cleared. */
      }
      clearForm();
      say("Draft discarded.");
      form.elements.body.focus();
    });
    // A URL selection applies once; later history restores use the latest saved draft.
    form.dataset.replyTargetExplicit = "false";
  });

  const clearAfterSignOut = () => {
    try {
      revoke(scope);
      shared.setItem(activeKey, "");
    } catch {
      send({ type: "logout" });
    }
    signedOut();
  };
  document.addEventListener("nurse:signed-out", clearAfterSignOut);
  document.querySelectorAll('form[action="/auth/logout"]').forEach((form) => {
    form.addEventListener("submit", () => {
      if (!form.hasAttribute("data-feedback-form")) clearAfterSignOut();
    });
  });
  const checkSession = () => {
    if (!enabled || !scope) return;
    try {
      if (!currentSession()) signedOut();
    } catch {
      unavailable();
    }
  };
  window.addEventListener("storage", (event) => {
    if (
      event.key === activeKey ||
      event.key === revokedKey(scope) ||
      event.key === null
    )
      checkSession();
  });
  channel?.addEventListener("message", (event) => {
    if (event.data?.scope !== scope) return;
    if (event.data.type === "logout") signedOut();
    if (event.data.type === "published" && enabled) {
      try {
        acknowledge(event.data.confirmation);
      } catch {
        unavailable();
      }
    }
  });
  window.addEventListener("pageshow", () => {
    checkSession();
    // Browsers can restore form fields after pageshow even without the back/forward cache.
    // Let that restoration finish, then reconcile against our saved/cleared draft state.
    setTimeout(() => {
      if (enabled) {
        try {
          controllers.forEach((controller) => controller.resume());
        } catch {
          unavailable();
        }
      }
    }, 0);
  });
  window.addEventListener("focus", checkSession);
})();
