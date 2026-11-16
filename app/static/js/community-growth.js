(() => {
  "use strict";
  document.querySelectorAll("[data-share-url]").forEach((container) => {
    const url = new URL(container.dataset.shareUrl, location.origin).href;
    const title = container.dataset.shareTitle || "Nurse.ng community";
    const status = container.querySelector("[data-share-status]");
    const native = container.querySelector("[data-native-share]");
    const copy = container.querySelector("[data-copy-share]");
    const say = (message) => { status.textContent = message; };
    if (typeof navigator.share === "function") {
      native.hidden = false;
      native.addEventListener("click", async () => {
        try {
          await navigator.share({ title, text: title, url });
          say("Sharing opened.");
        } catch (error) {
          say(error.name === "AbortError" ? "Sharing cancelled." : "Choose WhatsApp or copy the invitation link.");
        }
      });
    }
    copy.addEventListener("click", async () => {
      try {
        if (!navigator.clipboard?.writeText) throw new Error("Clipboard unavailable");
        await navigator.clipboard.writeText(url);
        say("Invitation link copied. Share it with a colleague.");
      } catch {
        const fallback = container.querySelector("[data-share-fallback]");
        fallback.hidden = false;
        const input = fallback.querySelector("input");
        input.value = url;
        input.focus(); input.select();
        say("Select and copy the invitation link shown below.");
      }
    });
  });
  document.querySelectorAll("[data-community-post-kind]").forEach((select) => {
    const form = select.form;
    const refresh = () => {
      const activity = select.value === "activity";
      form.querySelector("[data-activity-fields]").hidden = !activity;
      form.querySelector("[data-activity-title]").required = activity;
      form.querySelector("[data-title-optional]").hidden = activity;
      form.elements.activity_format.required = activity;
      form.elements.activity_format.disabled = !activity;
      form.elements.activity_starts_at.disabled = !activity;
    };
    form.addEventListener("change", refresh);
    form.addEventListener("input", refresh);
    form.addEventListener("community:reply-context", refresh);
    refresh();
  });
})();
