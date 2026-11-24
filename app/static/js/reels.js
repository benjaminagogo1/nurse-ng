/**
 * Enhance Reel playback, captions, visibility, uploads and explicit drafts; server processing decides readiness.
 * Maintainer map: docs/FRONTEND_GUIDE.md and docs/reference/FRONTEND.md.
 */
(() => {
  "use strict";
  const notice = document.querySelector("[data-reel-notice]");
  const announce = (text, error = false) => {
    if (!notice) return;
    notice.textContent = text;
    notice.hidden = false;
    notice.setAttribute("role", error ? "alert" : "status");
  };
  const viewer = document.querySelector("[data-reels-viewer]");
  const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
  let active = null;
  let visible = true;
  let sound = false;
  let saver =
    navigator.connection?.saveData ||
    ["slow-2g", "2g", "3g"].includes(navigator.connection?.effectiveType);
  try {
    saver = localStorage.getItem("nurse-reels-data") === "on" || saver;
  } catch {
    /* Optional preference. */
  }
  const dialogs = [...document.querySelectorAll(".reel-dialog")];
  const modalOpen = () => document.querySelector("dialog[open]") !== null;
  const pauseAll = () =>
    viewer?.querySelectorAll("video").forEach((video) => video.pause());
  const play = (video) => {
    if (!video || document.hidden || !visible || modalOpen()) return;
    video.play().catch(() => {
      /* A visible Play button handles autoplay restrictions. */
    });
  };
  const activate = (tile) => {
    if (!tile || tile === active) return;
    pauseAll();
    active = tile;
    viewer.querySelectorAll("[data-reel]").forEach((other) => {
      const video = other.querySelector("video");
      if (other !== tile && video.hasAttribute("src")) {
        video.removeAttribute("src");
        video.load();
      }
      other.toggleAttribute("data-active", other === tile);
    });
    const video = tile.querySelector("video");
    video.src = saver ? video.dataset.low : video.dataset.main;
    video.muted = !sound;
    if (!saver && !reducedMotion) play(video);
  };
  const move = (amount) => {
    if (!viewer) return;
    const tiles = [...viewer.querySelectorAll("[data-reel]")];
    const next =
      tiles[
        Math.max(0, Math.min(tiles.length - 1, tiles.indexOf(active) + amount))
      ];
    if (next)
      viewer.scrollTo({
        top: next.offsetTop,
        behavior: reducedMotion ? "instant" : "smooth",
      });
  };
  if (viewer && "IntersectionObserver" in window) {
    const tiles = [...viewer.querySelectorAll("[data-reel]")];
    viewer.style.position = "relative";
    const size = () => {
      const top = Math.max(0, viewer.getBoundingClientRect().top);
      viewer.style.setProperty(
        "--reel-height",
        Math.min(780, Math.max(490, innerHeight - top - 18)) + "px",
      );
    };
    size();
    window.addEventListener("resize", size);
    viewer.querySelectorAll("[data-reel-controls]").forEach((control) => {
      control.hidden = false;
    });
    document.querySelectorAll(".reels-step-controls").forEach((control) => {
      control.hidden = false;
    });
    tiles.forEach((tile) => {
      const video = tile.querySelector("video");
      video.controls = false;
      video.removeAttribute("src");
      video.load();
      const playButton = tile.querySelector("[data-play]");
      const updatePlay = () => {
        playButton.querySelector("[data-play-label]").textContent = video.paused
          ? "Play"
          : "Pause";
        playButton.setAttribute(
          "aria-label",
          video.paused ? "Play video" : "Pause video",
        );
      };
      video.addEventListener("play", () => {
        if (tile !== active || document.hidden || modalOpen()) video.pause();
        else
          viewer.querySelectorAll("video").forEach((other) => {
            if (other !== video) other.pause();
          });
        updatePlay();
      });
      video.addEventListener("pause", updatePlay);
      video.addEventListener("error", () => {
        if (video.hasAttribute("src"))
          tile.querySelector("[data-playback-error]").hidden = false;
      });
      video.addEventListener("playing", () => {
        tile.querySelector("[data-playback-error]").hidden = true;
      });
      const togglePlay = () => {
        activate(tile);
        if (video.error) video.load();
        if (video.paused) play(video);
        else video.pause();
      };
      playButton.addEventListener("click", togglePlay);
      video.addEventListener("click", togglePlay);
      tile.querySelector("[data-mute]").addEventListener("click", () => {
        sound = !sound;
        viewer.querySelectorAll("video").forEach((v) => {
          v.muted = !sound;
        });
        viewer.querySelectorAll("[data-mute]").forEach((button) => {
          button.setAttribute("aria-pressed", String(sound));
          button.setAttribute(
            "aria-label",
            sound ? "Turn sound off" : "Turn sound on",
          );
          button.querySelector("[data-sound-label]").textContent = sound
            ? "Sound on"
            : "Sound off";
        });
      });
      tile
        .querySelector("[data-captions]")
        ?.addEventListener("click", (event) => {
          const button = event.currentTarget;
          const on = button.getAttribute("aria-pressed") !== "true";
          button.setAttribute("aria-pressed", String(on));
          if (video.textTracks[0])
            video.textTracks[0].mode = on ? "showing" : "hidden";
        });
      video.querySelector("track")?.addEventListener("load", () => {
        // Keep timed captions above the custom sound and seek controls.
        for (const cue of video.textTracks[0]?.cues || []) {
          cue.snapToLines = false;
          cue.line = 70;
        }
      });
      const seek = document.createElement("input");
      seek.type = "range";
      seek.min = "0";
      seek.max = "100";
      seek.value = "0";
      seek.step = "0.1";
      seek.className = "reel-seek";
      seek.setAttribute("aria-label", "Video position");
      tile.querySelector(".reel-playback").append(seek);
      video.addEventListener("timeupdate", () => {
        if (
          Number.isFinite(video.duration) &&
          document.activeElement !== seek
        ) {
          seek.value = String((video.currentTime / video.duration) * 100);
          seek.setAttribute(
            "aria-valuetext",
            Math.floor(video.currentTime) +
              " of " +
              Math.ceil(video.duration) +
              " seconds",
          );
        }
      });
      seek.addEventListener("input", () => {
        if (Number.isFinite(video.duration))
          video.currentTime = (video.duration * Number(seek.value)) / 100;
      });
    });
    const observer = new IntersectionObserver(
      (entries) => {
        const candidate = entries
          .filter((entry) => entry.intersectionRatio > 0.6)
          .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
        if (candidate) activate(candidate.target);
        else if (
          active &&
          active.getBoundingClientRect().bottom <=
            viewer.getBoundingClientRect().top
        )
          pauseAll();
      },
      { root: viewer, threshold: [0.1, 0.6, 0.9] },
    );
    tiles.forEach((tile) => observer.observe(tile));
    const outer = new IntersectionObserver(
      (entries) => {
        visible = entries[0].isIntersecting;
        if (!visible) pauseAll();
      },
      { threshold: 0.15 },
    );
    outer.observe(viewer);
    viewer.addEventListener("keydown", (event) => {
      if (event.target.closest("input, textarea, select, button, a, summary"))
        return;
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        move(event.key === "ArrowDown" ? 1 : -1);
      }
      if (event.key === " ") {
        event.preventDefault();
        active?.querySelector("[data-play]").click();
      }
    });
    document
      .querySelector("[data-next]")
      ?.addEventListener("click", () => move(1));
    document
      .querySelector("[data-previous]")
      ?.addEventListener("click", () => move(-1));
    const dataButton = document.querySelector("[data-data-saver]");
    if (dataButton) {
      dataButton.hidden = false;
      const label = () => {
        dataButton.setAttribute("aria-pressed", String(saver));
        dataButton.querySelector("span").textContent = saver
          ? "Data saver on"
          : "Data saver off";
      };
      label();
      dataButton.addEventListener("click", () => {
        saver = !saver;
        label();
        try {
          localStorage.setItem("nurse-reels-data", saver ? "on" : "off");
        } catch {
          /* Optional preference. */
        }
        if (active) {
          const tile = active;
          active = null;
          activate(tile);
        }
        announce(
          saver
            ? "Data saver is on. Smaller videos load when selected. Tap Play to watch."
            : "Data saver is off. Standard quality and muted autoplay are available.",
        );
      });
    }
  }
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) pauseAll();
  });
  window.addEventListener("pagehide", pauseAll);
  // Navigation and display dialogs also pause playback.
  document.querySelectorAll("dialog").forEach((dialog) =>
    new MutationObserver(() => {
      if (dialog.open) pauseAll();
    }).observe(dialog, { attributes: true, attributeFilter: ["open"] }),
  );
  dialogs.forEach((dialog) => {
    dialog
      .querySelector("[data-close-dialog]")
      ?.addEventListener("click", () => dialog.close());
  });
  let commentTile = null;
  async function loadComments(url) {
    const response = await fetch(url, {
      headers: { Accept: "text/html" },
      cache: "no-store",
    });
    if (!response.ok || response.redirected)
      throw new Error("Comments could not load. Please try again.");
    document.querySelector("[data-comments-body]").innerHTML =
      await response.text();
  }
  document.querySelectorAll("[data-comments]").forEach((link) =>
    link.addEventListener("click", async (event) => {
      const dialog = document.getElementById("reel-comments");
      if (!dialog?.showModal) return;
      event.preventDefault();
      pauseAll();
      commentTile = link.closest("[data-reel]");
      const body = document.querySelector("[data-comments-body]");
      body.textContent = "Loading conversation…";
      dialog.showModal();
      try {
        await loadComments(link.dataset.comments);
      } catch (error) {
        body.textContent = error.message;
      }
    }),
  );
  document.querySelectorAll("[data-report]").forEach((link) =>
    link.addEventListener("click", (event) => {
      const dialog = document.getElementById("reel-report");
      if (!dialog?.showModal) return;
      event.preventDefault();
      pauseAll();
      const form = dialog.querySelector("form");
      form.reset();
      form.action = "/reels/" + link.dataset.report + "/report";
      form.querySelector("[data-dialog-feedback]").textContent = "";
      dialog.showModal();
    }),
  );
  document.querySelectorAll("[data-share]").forEach((link) =>
    link.addEventListener("click", async (event) => {
      if (!navigator.share && !navigator.clipboard) return;
      event.preventDefault();
      pauseAll();
      try {
        if (navigator.share)
          await navigator.share({
            title: "A reel on Nurse.ng",
            url: link.href,
          });
        else {
          await navigator.clipboard.writeText(link.href);
          announce("Reel link copied. It is ready to share.");
        }
      } catch (error) {
        if (error.name !== "AbortError")
          announce(
            "Sharing was unavailable. Open the reel and copy its address.",
            true,
          );
      }
    }),
  );
  document.addEventListener("submit", async (event) => {
    const form = event.target.closest("[data-reel-action]");
    if (!form || !window.fetch) return;
    event.preventDefault();
    if (form.dataset.busy) return;
    form.dataset.busy = "yes";
    const button = form.querySelector('[type="submit"]');
    const feedback = form.querySelector("[data-dialog-feedback]");
    const action = form.dataset.reelAction;
    const originalLabel = button.innerHTML;
    button.disabled = true;
    if (feedback) feedback.textContent = "Sending…";
    try {
      const response = await fetch(form.action, {
        method: "POST",
        body: new FormData(form),
        headers: { "X-Reel-Action": "1" },
      });
      if (response.redirected)
        throw new Error(
          "Please sign in again to continue. Your text is still here.",
        );
      const result = await response.json();
      if (!response.ok)
        throw new Error(
          typeof result.detail === "string"
            ? result.detail
            : "This action could not be completed. Please try again.",
        );
      if (action === "save") {
        form.elements.saved.value = result.saved ? "no" : "yes";
        button.setAttribute("aria-pressed", String(result.saved));
        button.querySelector("[data-save-label]").textContent = result.saved
          ? "Saved"
          : "Save";
      } else if (action === "follow") {
        const creator = form.closest("[data-creator]").dataset.creator;
        document.querySelectorAll("[data-creator]").forEach((tile) => {
          if (tile.dataset.creator !== creator) return;
          const sibling = tile.querySelector('[data-reel-action="follow"]');
          if (!sibling) return;
          sibling.elements.following.value = result.following ? "no" : "yes";
          sibling.querySelector("button").textContent = result.following
            ? "Following"
            : "Follow";
          sibling
            .querySelector("button")
            .setAttribute("aria-pressed", String(result.following));
        });
      } else if (action === "comment") {
        form.elements.body.value = "";
        const count = commentTile?.querySelector("[data-reply-count]");
        if (count) count.textContent = String(Number(count.textContent) + 1);
        if (feedback) feedback.textContent = result.message;
        try {
          await loadComments(
            commentTile.querySelector("[data-comments]").dataset.comments,
          );
          document.querySelector(
            "#reel-comments [data-dialog-feedback]",
          ).textContent = result.message;
        } catch {
          if (feedback)
            feedback.textContent =
              "Comment posted. Reopen the conversation to see it.";
        }
      } else if (action === "report") {
        form.closest("dialog").close();
        form.reset();
      }
      if (action !== "comment") announce(result.message);
    } catch (error) {
      const text =
        error instanceof TypeError
          ? "We could not confirm the result. Check your connection before trying again."
          : error.message;
      if (feedback) feedback.textContent = text;
      else announce(text, true);
    } finally {
      button.disabled = false;
      delete form.dataset.busy;
      if (action === "comment" || action === "report")
        button.innerHTML = originalLabel;
    }
  });

  const upload = document.querySelector("[data-reel-upload]");
  if (upload && window.XMLHttpRequest) {
    const input = upload.querySelector("#reel-file");
    const preview = upload.querySelector("[data-upload-preview]");
    const cover = upload.querySelector("#reel-cover");
    const progress = upload.querySelector("[data-upload-progress]");
    let objectURL = null,
      busy = false;
    const showError = (body) =>
      document.dispatchEvent(
        new CustomEvent("nurse:feedback", {
          detail: { tone: "error", title: "Check your reel", body },
        }),
      );
    input.addEventListener("change", () => {
      if (objectURL) URL.revokeObjectURL(objectURL);
      preview.pause();
      preview.removeAttribute("src");
      preview.hidden = true;
      input.setCustomValidity("");
      cover.value = "0";
      upload.querySelector("[data-cover-label]").textContent = "0s";
      const file = input.files[0];
      if (!file) return;
      if (file.size > Number(upload.dataset.maxBytes)) {
        input.setCustomValidity("Choose a video within the upload size limit.");
        showError(input.validationMessage);
        return;
      }
      objectURL = URL.createObjectURL(file);
      preview.src = objectURL;
      preview.hidden = false;
    });
    preview.addEventListener("loadedmetadata", () => {
      if (preview.duration > Number(upload.dataset.maxSeconds)) {
        input.setCustomValidity(
          "Your video is too long. Choose a shorter clip.",
        );
        showError(input.validationMessage);
      } else input.setCustomValidity("");
      cover.max = String(Math.max(0, Math.ceil(preview.duration) - 1));
    });
    preview.addEventListener("error", () => {
      if (preview.hasAttribute("src"))
        showError(
          "Your browser cannot preview this file. The video worker will check whether it can be converted.",
        );
    });
    cover.addEventListener("input", () => {
      upload.querySelector("[data-cover-label]").textContent =
        cover.value + "s";
      if (Number.isFinite(preview.duration)) {
        preview.pause();
        preview.currentTime = Number(cover.value);
      }
    });
    upload.addEventListener("submit", (event) => {
      event.preventDefault();
      if (busy || !upload.reportValidity()) return;
      if (!navigator.onLine) {
        showError(
          "You are offline. Reconnect and try again. Your entries are still here.",
        );
        return;
      }
      busy = true;
      const button = upload.querySelector('[type="submit"]');
      const original = button.innerHTML;
      const data = new FormData(upload);
      button.disabled = true;
      button.textContent = "Uploading…";
      upload.setAttribute("aria-busy", "true");
      progress.hidden = false;
      const bar = progress.querySelector("progress");
      bar.value = 0;
      progress.querySelector("[data-upload-status]").textContent =
        "Uploading your video…";
      const xhr = new XMLHttpRequest();
      xhr.open("POST", upload.action);
      xhr.setRequestHeader("X-Reel-Upload", "1");
      xhr.timeout = 15 * 60 * 1000;
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) {
          bar.value = Math.round((e.loaded / e.total) * 100);
          progress.querySelector("[data-upload-status]").textContent =
            bar.value < 100
              ? "Uploading your video… " + bar.value + "%"
              : "Upload sent. Waiting for confirmation…";
        }
      };
      const uncertain = () =>
        showError(
          "We could not confirm your upload. Check My reels before trying again. Retrying this form will not publish the same upload twice.",
        );
      xhr.onerror = uncertain;
      xhr.ontimeout = uncertain;
      xhr.onload = async () => {
        try {
          const result = JSON.parse(xhr.responseText);
          if (
            xhr.status >= 200 &&
            xhr.status < 300 &&
            /^\/reels\/[a-f0-9-]+\/status$/.test(result.redirect)
          ) {
            await window.NurseOffline?.acknowledgeConnected?.(upload, {
              body: data.get("body"),
              upload_key: data.get("upload_key"),
            })?.catch(() => {});
            location.assign(result.redirect);
          } else
            showError(
              result.error ||
                "Your session or upload could not be verified. Check My reels or sign in again.",
            );
        } catch {
          uncertain();
        }
      };
      xhr.onloadend = () => {
        busy = false;
        button.disabled = false;
        button.innerHTML = original;
        upload.removeAttribute("aria-busy");
        progress.hidden = true;
      };
      xhr.send(data);
    });
    window.addEventListener("beforeunload", (event) => {
      if (busy) {
        event.preventDefault();
        event.returnValue = "";
      }
    });
    window.addEventListener("pagehide", () => {
      if (objectURL) URL.revokeObjectURL(objectURL);
    });
  }
  const status = document.querySelector("[data-processing-status]");
  if (status && ["queued", "processing"].includes(status.dataset.state)) {
    let timer,
      polls = 0;
    const poll = async () => {
      if (document.hidden) {
        timer = setTimeout(poll, 5000);
        return;
      }
      try {
        const response = await fetch(status.dataset.processingStatus, {
          headers: { Accept: "application/json" },
          cache: "no-store",
        });
        if (!response.ok || response.redirected)
          throw new Error("Status unavailable");
        const data = await response.json();
        status.querySelector("[data-status-connection]").hidden = true;
        status.dataset.state = data.state;
        if (data.state === "ready" || data.state === "failed") {
          status.querySelector("[data-status-title]").textContent =
            data.state === "ready"
              ? "Your reel is live"
              : "Your video needs attention";
          status.querySelector("[data-status-body]").textContent =
            data.state === "ready"
              ? "Your video is public in Reels, the Community feed and your selected topic. Anyone can watch and share it."
              : data.error;
          status.querySelector("[data-watch-reel]").hidden =
            data.state !== "ready";
          const retry = status.querySelector("[data-retry-reel]");
          if (retry) retry.hidden = !data.can_retry;
          status
            .querySelectorAll("[data-step]")
            .forEach((step) =>
              step.classList.toggle(
                "is-done",
                step.dataset.step === "uploaded" || data.state === "ready",
              ),
            );
          return;
        }
        if (data.state === "processing")
          status.querySelector("[data-status-body]").textContent =
            "We are preparing your video and cover image. You can leave this page and return from My reels.";
      } catch {
        status.querySelector("[data-status-connection]").hidden = false;
      }
      polls += 1;
      if (polls < 240) timer = setTimeout(poll, 5000);
      else status.querySelector("[data-status-connection]").hidden = false;
    };
    timer = setTimeout(poll, 2500);
    window.addEventListener("pagehide", () => clearTimeout(timer));
  }
})();
