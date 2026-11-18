(() => {
  "use strict";
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const pad = (value) => String(value).padStart(2, "0");
  function format(value) {
    if (!value) return "";
    const normalized = /(?:Z|[+-]\d\d:\d\d)$/.test(value) ? value : value + "Z";
    const date = new Date(normalized);
    if (Number.isNaN(date.getTime())) return String(value);
    const hour = date.getUTCHours();
    return `${pad(date.getUTCDate())} ${months[date.getUTCMonth()]} ${date.getUTCFullYear()} ${pad(hour % 12 || 12)}:${pad(date.getUTCMinutes())} ${hour < 12 ? "AM" : "PM"}`;
  }
  window.NurseTime = Object.freeze({ format });
})();
