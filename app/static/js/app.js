(() => {
  "use strict";
  const toggle = document.querySelector(".nav-toggle");
  const menu =
    toggle && document.getElementById(toggle.getAttribute("aria-controls"));
  const navigationDialog = document.getElementById("mobile-navigation");
  const mobile = matchMedia("(max-width: 899px)");
  const menuAnchor = document.createComment("navigation position");
  if (menu) menu.before(menuAnchor);
  const setMenu = (open, focus = false) => {
    if (!menu || !navigationDialog?.showModal) return;
    if (open && mobile.matches) navigationDialog.showModal();
    else navigationDialog.close();
    if (toggle) {
      toggle.setAttribute("aria-expanded", String(navigationDialog.open));
      toggle.setAttribute(
        "aria-label",
        navigationDialog.open ? "Close menu" : "Open menu",
      );
      if (focus) toggle.focus();
    }
  };
  const placeMenu = () => {
    if (!menu || !navigationDialog?.showModal) return;
    setMenu(false);
    if (mobile.matches) {
      navigationDialog.querySelector("[data-navigation-content]").append(menu);
      toggle.setAttribute("aria-controls", "mobile-navigation");
      toggle.setAttribute("aria-haspopup", "dialog");
    } else {
      menuAnchor.after(menu);
      toggle.setAttribute("aria-controls", menu.id);
      toggle.removeAttribute("aria-haspopup");
    }
  };
  placeMenu();
  mobile.addEventListener("change", placeMenu);
  toggle?.addEventListener("click", () => setMenu(!navigationDialog.open));
  navigationDialog
    ?.querySelector("[data-navigation-close]")
    ?.addEventListener("click", () => setMenu(false, true));
  navigationDialog?.addEventListener("close", () => {
    toggle?.setAttribute("aria-expanded", "false");
    toggle?.setAttribute("aria-label", "Open menu");
  });
  navigationDialog?.addEventListener("click", (event) => {
    if (event.target !== navigationDialog) return;
    const bounds = navigationDialog.getBoundingClientRect();
    if (
      event.clientX < bounds.left ||
      event.clientX > bounds.right ||
      event.clientY < bounds.top ||
      event.clientY > bounds.bottom
    )
      setMenu(false, true);
  });
  document
    .querySelectorAll(".sidebar a, .site-nav a")
    .forEach((link) => link.addEventListener("click", () => setMenu(false)));
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      document.querySelectorAll(".header-popover[open]").forEach((popover) => {
        const hadFocus = popover.contains(document.activeElement);
        popover.open = false;
        if (hadFocus) popover.querySelector("summary").focus();
      });
    }
  });
  document.addEventListener("click", (event) => {
    document.querySelectorAll(".header-popover[open]").forEach((menu) => {
      if (!menu.contains(event.target)) menu.open = false;
    });
  });
  document.querySelectorAll(".header-popover").forEach((menu) =>
    menu.addEventListener("toggle", () => {
      if (menu.open)
        document.querySelectorAll(".header-popover[open]").forEach((other) => {
          if (other !== menu) other.open = false;
        });
    }),
  );
  const error = document.querySelector('main .form-error[role="alert"]');
  if (error) {
    error.tabIndex = -1;
    error.focus();
  }
  document
    .querySelector(".skip-link")
    ?.addEventListener("click", () => document.getElementById("main")?.focus());
  document.querySelectorAll("[data-toggle-password]").forEach((button) => {
    button.addEventListener("click", () => {
      const input = document.getElementById(button.dataset.togglePassword);
      const visible = input.type === "password";
      input.type = visible ? "text" : "password";
      button.setAttribute(
        "aria-label",
        visible ? "Hide password" : "Show password",
      );
      button.setAttribute("aria-pressed", String(visible));
    });
  });
  document.querySelectorAll("[data-greeting]").forEach((label) => {
    const hour = new Date().getHours();
    label.textContent =
      hour < 12
        ? "Good morning"
        : hour < 17
          ? "Good afternoon"
          : "Good evening";
  });
  document.querySelectorAll('.slot input[type="file"]').forEach((input) => {
    input.addEventListener("change", () => {
      const slot = input.closest(".slot");
      const hint = slot.querySelector("[data-hint]");
      const file = input.files[0];
      slot.classList.toggle("has-file", Boolean(file));
      if (hint) hint.textContent = file ? file.name : hint.dataset.hint;
      slot.querySelector(".slot-btn > span").textContent = file
        ? "Change"
        : "Upload";
    });
  });
  document
    .querySelectorAll('.pf .section-tabs a[href^="#"]')
    .forEach((link) => {
      link.addEventListener("click", () => {
        document
          .querySelectorAll(".pf .section-tabs a")
          .forEach((item) => item.removeAttribute("aria-current"));
        link.setAttribute("aria-current", "page");
      });
    });
})();
