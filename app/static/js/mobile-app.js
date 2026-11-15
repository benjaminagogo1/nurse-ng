(() => {
  "use strict";
  // The downloaded native app already contains the website's account and features.
  const native = window.Capacitor?.isNativePlatform?.() === true;
  document.querySelectorAll("[data-mobile-install]").forEach((card) => {
    card.hidden = native;
  });
})();
