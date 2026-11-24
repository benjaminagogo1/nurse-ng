(() => {
  "use strict";
  const carousel = document.querySelector("[data-home-carousel]");
  if (!carousel) return;
  const slides = Array.from(carousel.querySelectorAll("[data-hero-slide]"));
  const controls = carousel.querySelector("[data-hero-controls]");
  const dots = Array.from(controls.querySelectorAll("[data-hero-go]"));
  const pause = controls.querySelector("[data-hero-pause]");
  const status = carousel.querySelector("[data-hero-status]");
  const root = document.documentElement;
  const interval = 5000;
  let current = 0;
  let timer;
  let requested = root.dataset.motion !== "reduce";
  let inView = true;

  

  const updatePause = () => {
    pause.setAttribute("aria-label", requested ? "Pause automatic slides" : "Play automatic slides");
    pause.querySelector("[data-hero-pause-label]").textContent = requested ? "Pause" : "Play";
    pause.querySelector("[data-hero-pause-icon]").hidden = !requested;
    pause.querySelector("[data-hero-play-icon]").hidden = requested;
  };
  const schedule = () => {
    clearTimeout(timer);
    if (requested && inView && !document.hidden) {
      timer = setTimeout(() => show(current + 1), interval);
    }
  };
  const stop = () => {
    requested = false;
    updatePause();
    schedule();
  };
  const show = (index, manual = false) => {
    current = (index + slides.length) % slides.length;
    slides.forEach((slide, position) => {
      const active = position === current;
      slide.setAttribute("aria-hidden", String(!active));
      slide.inert = !active;
      dots[position].setAttribute("aria-current", String(active));
    });
    carousel.dataset.active = slides[current].dataset.heroSlide;
    if (manual) status.textContent = slides[current].getAttribute("aria-label");
    updatePause();
    schedule();
  };

  show(0);
  controls.hidden = false;
  carousel.classList.add("is-ready");
  // Commit initial visibility before enabling fades to avoid a flash on refresh.
  void carousel.offsetWidth;
  carousel.classList.add("is-animated");
  controls.querySelector("[data-hero-prev]").addEventListener("click", () => show(current - 1, true));
  controls.querySelector("[data-hero-next]").addEventListener("click", () => show(current + 1, true));
  dots.forEach((dot, index) => dot.addEventListener("click", () => show(index, true)));
  pause.addEventListener("click", () => {
    requested = !requested;
    updatePause();
    schedule();
  });
  controls.addEventListener("keydown", (event) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    show(current + (event.key === "ArrowRight" ? 1 : -1), true);
  });
  // Keep slide content steady while someone uses search or follows a link.
  // Carousel controls reset the timer; Pause remains an explicit choice.
  carousel.addEventListener("focusin", (event) => {
    if (event.target.closest("[data-hero-slide]")) stop();
  });
  document.addEventListener("visibilitychange", schedule);
  window.addEventListener("pageshow", schedule);
  window.addEventListener("pagehide", () => clearTimeout(timer));
  new IntersectionObserver(([entry]) => {
    inView = entry.isIntersecting;
    schedule();
  }).observe(carousel);
  new MutationObserver(() => {
    if (root.dataset.motion === "reduce") stop();
  }).observe(root, { attributes: true, attributeFilter: ["data-motion"] });
})();
