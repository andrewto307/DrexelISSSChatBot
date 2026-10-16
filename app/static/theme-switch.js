"use strict";

(() => {
  const THEME_KEY = "isss.theme";
  const buttons = Array.from(document.querySelectorAll("[data-theme-choice]"));
  const systemDark = window.matchMedia("(prefers-color-scheme: dark)");

  function themeChoice() {
    return document.documentElement.getAttribute("data-theme-choice") || "system";
  }

  function applyTheme(choice) {
    const dark = choice === "dark" || (choice === "system" && systemDark.matches);
    document.documentElement.setAttribute("data-theme", dark ? "dark" : "light");
    document.documentElement.setAttribute("data-theme-choice", choice);
    for (const button of buttons) {
      const selected = button.dataset.themeChoice === choice;
      button.setAttribute("aria-checked", String(selected));
      button.tabIndex = selected ? 0 : -1;
    }
  }

  function chooseTheme(choice) {
    try {
      if (choice === "system") window.localStorage.removeItem(THEME_KEY);
      else window.localStorage.setItem(THEME_KEY, choice);
    } catch {
      // Private windows can block storage; the choice still applies to this page.
    }
    applyTheme(choice);
  }

  buttons.forEach((button, index) => {
    button.addEventListener("click", () => chooseTheme(button.dataset.themeChoice));
    button.addEventListener("keydown", (event) => {
      const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[event.key];
      if (!step) return;
      event.preventDefault();
      const next = buttons[(index + step + buttons.length) % buttons.length];
      chooseTheme(next.dataset.themeChoice);
      next.focus();
    });
  });
  systemDark.addEventListener("change", () => {
    if (themeChoice() === "system") applyTheme("system");
  });
  applyTheme(themeChoice());
})();
