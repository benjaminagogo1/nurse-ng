/**
 * Progressive enhancement for professional learning pages.
 *
 * Native form posts, server validation and persisted learning state remain the
 * source of truth. This module never stores quiz answers, drafts, credentials or
 * room media in browser storage. The separate education-room.js controller owns
 * classroom networking and controls; do not intercept its message form here.
 * The server-rendered baseline remains usable when this module cannot load.
 */
(() => {
  "use strict";

  const page = document.querySelector(".edu-page");
  if (!page) return;

  /** Show a visual character counter without announcing every keystroke.
   * Existing labels/hints keep their accessible IDs; the counter is additional
   * help, not a replacement for maxlength or server-side size validation.
   */
  function enhanceCharacterCounts() {
    page.querySelectorAll(".edu-form textarea[maxlength]").forEach((textarea) => {
      const limit = Number(textarea.maxLength);
      if (!Number.isFinite(limit) || limit <= 0) return;
      const counter = document.createElement("span");
      counter.className = "edu-character-count";
      counter.setAttribute("aria-hidden", "true");
      textarea.insertAdjacentElement("afterend", counter);
      const update = () => {
        counter.textContent = `${textarea.value.length.toLocaleString()} / ${limit.toLocaleString()}`;
      };
      textarea.addEventListener("input", update);
      update();
    });
  }

  /** Use the actual written choices in the correct-answer selector.
   * The backend accepts newline-separated answer choices and a zero-based
   * correct_index. Labels remain understandable to an educator; user content is
   * assigned with textContent/Option rather than interpolated HTML.
   */
  function enhanceQuestionAuthoring() {
    page.querySelectorAll("[data-correct-answer-select]").forEach((select) => {
      const form = select.closest("form");
      const optionsField = form?.querySelector('textarea[name="options"]');
      if (!optionsField) return;
      const update = () => {
        const choices = optionsField.value.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
        if (!choices.length) return;
        const previous = Number(select.value);
        select.replaceChildren();
        choices.forEach((choice, index) => {
          const preview = choice.length > 75 ? `${choice.slice(0, 72)}…` : choice;
          select.add(new Option(`Answer ${index + 1}: ${preview}`, String(index)));
        });
        select.value = String(Math.min(Math.max(previous || 0, 0), choices.length - 1));
      };
      optionsField.addEventListener("input", update);
      update();
    });
  }

  /** Both datetime-local fields use the timezone selected in the same form.
   * Their ISO local values can be compared directly. This improves native
   * validation without converting them through the browser's different timezone;
   * the server handles timezone conversion, daylight-saving gaps and duration.
   */
  function enhanceScheduling() {
    page.querySelectorAll("[data-education-schedule]").forEach((form) => {
      const start = form.querySelector('input[name="starts_at"]');
      const end = form.querySelector('input[name="ends_at"]');
      if (!start || !end) return;
      const update = () => {
        end.min = start.value || "";
        end.setCustomValidity(start.value && end.value && end.value <= start.value
          ? "Choose an ending time after the starting time."
          : "");
      };
      start.addEventListener("input", update);
      end.addEventListener("input", update);
      update();
    });
  }

  /** Confirm actions that affect other people's scheduled or live learning.
   * A native confirmation keeps keyboard/screen-reader support and requires no
   * additional modal lifecycle. Form fields and the submitter are left untouched
   * so ordinary server CSRF/action checks still apply.
   */
  function enhanceConfirmations() {
    page.querySelectorAll("form[data-education-confirm]").forEach((form) => {
      form.addEventListener("submit", (event) => {
        if (!window.confirm(form.dataset.educationConfirm)) event.preventDefault();
      });
    });
  }

  enhanceCharacterCounts();
  enhanceQuestionAuthoring();
  enhanceScheduling();
  enhanceConfirmations();
})();
