"use strict";

(() => {
  const EMAIL_KEY = "isss.authEmail";
  const RESEND_SECONDS = 60;
  const NETWORK_ERROR = "Couldn't reach the assistant. Check your connection and try again.";
  const MISSING = {
    email: "Enter your Drexel email.",
    password: "Enter a password.",
    code: "Enter the 6-digit code from the email.",
  };

  const views = new Map(Array.from(document.querySelectorAll("[data-view]"), (view) => [view.dataset.view, view]));
  const resendButtons = Array.from(document.querySelectorAll("[data-resend]"));
  const resendAvailableAt = {};
  let email = readEmail();
  let typedEmail = "";

  function readEmail() {
    try {
      return window.sessionStorage.getItem(EMAIL_KEY) || "";
    } catch {
      return "";
    }
  }

  function rememberEmail(value) {
    email = value;
    try {
      window.sessionStorage.setItem(EMAIL_KEY, value);
    } catch {
      return;
    }
  }

  function viewName() {
    const name = window.location.hash.slice(1);
    if (!views.has(name)) return "login";
    if (name === "verify" && !email) return "signup";
    if (name === "reset" && !email) return "forgot";
    return name;
  }

  function show() {
    const name = viewName();
    for (const [key, view] of views) view.hidden = key !== name;
    const view = views.get(name);
    for (const slot of view.querySelectorAll("[data-email]")) slot.textContent = email;
    for (const input of view.querySelectorAll('input[type="email"]')) {
      if (!input.value) input.value = typedEmail || email;
    }
    document.title = `${view.querySelector("h1").textContent} · ISSS Assistant`;
    const inputs = Array.from(view.querySelectorAll("input"));
    (inputs.find((input) => !input.value) || inputs[0])?.focus();
  }

  function go(name) {
    if (window.location.hash === `#${name}`) show();
    else window.location.hash = name;
  }

  function setStatus(name, text) {
    views.get(name).querySelector(".form-status").textContent = text;
  }

  async function post(path, body) {
    const response = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    let data = {};
    try {
      data = await response.json();
    } catch {
      data = {};
    }
    return { ok: response.ok, status: response.status, data };
  }

  function detail(result, fallback) {
    return typeof result.data.detail === "string" ? result.data.detail : fallback;
  }

  function enterChat() {
    try {
      window.sessionStorage.removeItem(EMAIL_KEY);
    } catch {
      // Nothing to clean up when storage is blocked.
    }
    window.location.replace("/");
  }


  function startCooldown(purpose) {
    resendAvailableAt[purpose] = Date.now() + RESEND_SECONDS * 1000;
    updateResendButtons();
  }

  function updateResendButtons() {
    for (const button of resendButtons) {
      const seconds = Math.ceil(((resendAvailableAt[button.dataset.resend] || 0) - Date.now()) / 1000);
      button.disabled = seconds > 0;
      button.textContent = seconds > 0 ? `Send a new code (${seconds}s)` : "Send a new code";
    }
  }

  window.setInterval(updateResendButtons, 1000);

  for (const button of resendButtons) {
    button.addEventListener("click", async () => {
      const purpose = button.dataset.resend;
      const view = purpose === "verify" ? "verify" : "reset";
      button.disabled = true;
      try {
        const result = await post(purpose === "verify" ? "/api/auth/resend" : "/api/auth/forgot", { email });
        if (!result.ok) {
          setStatus(view, detail(result, "Couldn't send a new code. Try again in a minute."));
          updateResendButtons();
          return;
        }
        startCooldown(purpose);
        setStatus(view, `We sent a new code to ${email}. Only the newest code works.`);
      } catch {
        setStatus(view, NETWORK_ERROR);
        updateResendButtons();
      }
    });
  }


  const handlers = {
    async login(fields) {
      const result = await post("/api/auth/login", fields);
      if (result.ok) return enterChat();
      if (result.status === 403) {
        rememberEmail(fields.email.trim().toLowerCase());
        startCooldown("verify");
        go("verify");
        setStatus("verify", detail(result, ""));
        return null;
      }
      return detail(result, "Couldn't log in. Try again.");
    },

    async signup(fields) {
      const result = await post("/api/auth/signup", fields);
      if (!result.ok) return detail(result, "Couldn't create your account. Try again.");
      rememberEmail(result.data.email);
      startCooldown("verify");
      setStatus("verify", "");
      go("verify");
      return null;
    },

    async verify(fields) {
      const result = await post("/api/auth/verify", { email, code: fields.code });
      if (result.ok) return enterChat();
      return detail(result, "Couldn't check that code. Try again.");
    },

    async forgot(fields) {
      const result = await post("/api/auth/forgot", fields);
      if (!result.ok) return detail(result, "Couldn't send a code. Try again.");
      rememberEmail(result.data.email);
      startCooldown("reset");
      setStatus("reset", "");
      go("reset");
      return null;
    },

    async reset(fields) {
      const result = await post("/api/auth/reset", { email, code: fields.code, password: fields.password });
      if (result.ok) return enterChat();
      return detail(result, "Couldn't set your password. Try again.");
    },
  };

  for (const form of document.querySelectorAll("[data-form]")) {
    const error = form.querySelector(".form-error");
    const submit = form.querySelector('button[type="submit"]');

    const showError = (text) => {
      error.textContent = text;
      error.hidden = false;
    };

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      error.hidden = true;
      const missing = Array.from(form.elements).find((field) => field.required && !field.value.trim());
      if (missing) {
        showError(MISSING[missing.name]);
        missing.focus();
        return;
      }
      submit.disabled = true;
      try {
        const problem = await handlers[form.dataset.form](Object.fromEntries(new FormData(form)));
        if (problem) showError(problem);
      } catch {
        showError(NETWORK_ERROR);
      } finally {
        submit.disabled = false;
      }
    });
  }

  document.addEventListener("input", (event) => {
    if (event.target.type === "email") typedEmail = event.target.value.trim();
  });
  window.addEventListener("hashchange", show);
  show();
})();
