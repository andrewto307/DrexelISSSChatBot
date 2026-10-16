"use strict";

(() => {
  const CONVERSATION_KEY = "isss.conversationId";
  const PENDING_QUESTION_KEY = "isss.pendingQuestion";
  const MAX_CHARACTERS = 1000;
  const COUNTER_FROM = 800;

  const ui = {
    thread: document.getElementById("thread"),
    welcome: document.getElementById("welcome"),
    form: document.getElementById("composer"),
    input: document.getElementById("question"),
    send: document.getElementById("send"),
    newChat: document.getElementById("new-chat"),
    counter: document.getElementById("char-count"),
    examples: Array.from(document.querySelectorAll(".example")),
    account: document.getElementById("account"),
    accountButton: document.getElementById("account-button"),
    accountPanel: document.getElementById("account-panel"),
    accountEmail: document.getElementById("account-email"),
    logOut: document.getElementById("log-out"),
    logIn: document.getElementById("log-in"),
  };

  const state = {
    conversationId: readStorage(window.sessionStorage, CONVERSATION_KEY),
    signedIn: null,
    busy: false,
    full: false,
    controller: null,
    followBottom: true,
  };

  const icons = {
    mark: svg('<circle cx="12" cy="12" r="9"/><path d="M3 12h18"/><path d="M12 3a14 14 0 0 1 0 18a14 14 0 0 1 0-18z"/>'),
    thumbsUp: svg('<path d="M7 11v9H4a1 1 0 0 1-1-1v-7a1 1 0 0 1 1-1h3z"/><path d="M7 11l4-8a2.5 2.5 0 0 1 2.5 2.5V9h5.3a2 2 0 0 1 2 2.4l-1.3 7A2 2 0 0 1 17.5 20H7"/>'),
    thumbsDown: svg('<path d="M17 13V4h3a1 1 0 0 1 1 1v7a1 1 0 0 1-1 1h-3z"/><path d="M17 13l-4 8a2.5 2.5 0 0 1-2.5-2.5V15H5.2a2 2 0 0 1-2-2.4l1.3-7A2 2 0 0 1 6.5 4H17"/>'),
    alert: svg('<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><path d="M12 9v4M12 17h.01"/>'),
    clock: svg('<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>'),
    info: svg('<circle cx="12" cy="12" r="9"/><path d="M12 16v-4M12 8h.01"/>'),
    update: svg('<path d="M20 11a8 8 0 0 0-14.3-4.9L4 8"/><path d="M4 4v4h4"/><path d="M4 13a8 8 0 0 0 14.3 4.9L20 16"/><path d="M20 20v-4h-4"/>', 14),
    check: svg('<path d="M20 6 9 17l-5-5"/>', 14),
    retry: svg('<path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 4v7h-7"/>', 16),
    plus: svg('<path d="M12 5v14M5 12h14"/>', 16),
    logIn: svg('<path d="M15 4h4v16h-4M10 8l4 4-4 4M14 12H4"/>', 16),
  };

  function svg(paths, size = 18) {
    return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths}</svg>`;
  }

  function readStorage(storage, key) {
    try {
      return storage.getItem(key);
    } catch {
      return null;
    }
  }

  function writeStorage(storage, key, value) {
    try {
      if (value === null) {
        storage.removeItem(key);
      } else {
        storage.setItem(key, value);
      }
    } catch {
      return;
    }
  }

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }


  function setSignedIn(signedIn, email = "") {
    state.signedIn = signedIn;
    ui.account.hidden = !signedIn;
    ui.logIn.hidden = signedIn;
    ui.accountEmail.textContent = email;
    if (!signedIn) {
      setAccountOpen(false);
      setConversation(null);
    }
  }


  window.DOMPurify.addHook("afterSanitizeAttributes", (node) => {
    if (node.tagName === "A") {
      node.setAttribute("target", "_blank");
      node.setAttribute("rel", "noopener noreferrer");
    }
  });

  function renderMarkdown(text) {
    return window.DOMPurify.sanitize(window.marked.parse(text, { gfm: true, breaks: false }));
  }


  function nearBottom() {
    return window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 160;
  }

  function scrollToEnd(force = false) {
    if (force || state.followBottom) {
      window.scrollTo({ top: document.documentElement.scrollHeight });
    }
  }

  window.addEventListener("scroll", () => {
    state.followBottom = nearBottom();
  }, { passive: true });


  function setConversation(id) {
    state.conversationId = id;
    writeStorage(window.sessionStorage, CONVERSATION_KEY, id);
  }

  function setBusy(busy) {
    state.busy = busy;
    for (const example of ui.examples) example.disabled = busy;
    updateComposer();
  }

  function updateComposer() {
    const length = ui.input.value.length;
    ui.send.disabled = state.busy || state.full || ui.input.value.trim().length === 0;
    ui.counter.hidden = length < COUNTER_FROM;
    ui.counter.textContent = `${length} / ${MAX_CHARACTERS}`;
    ui.input.style.height = "auto";
    ui.input.style.height = `${Math.min(ui.input.scrollHeight, 192)}px`;
  }

  function showWelcome(show) {
    ui.welcome.hidden = !show;
  }


  function addUserMessage(text, restored = false) {
    const item = element("li", "message message-user", text);
    if (restored) item.dataset.restored = "";
    ui.thread.append(item);
    return item;
  }

  function addAssistantMessage(restored = false) {
    const item = element("li", "message message-assistant");
    if (restored) item.dataset.restored = "";
    const label = element("div", "message-label");
    label.innerHTML = icons.mark;
    label.append(element("span", null, "ISSS Assistant"));
    const status = element("div", "status");
    status.innerHTML = '<span class="pulse" aria-hidden="true"></span>';
    status.append(element("span", null, "Searching ISSS pages…"));
    const body = element("div", "prose");
    item.append(label, status, body);
    ui.thread.append(item);
    return { item, status, body, frame: 0, pending: "" };
  }

  function scheduleRender(view, text) {
    view.pending = text;
    if (view.frame) return;
    view.frame = window.requestAnimationFrame(() => {
      view.frame = 0;
      view.body.innerHTML = renderMarkdown(view.pending);
      scrollToEnd();
    });
  }

  function formatDate(isoDate) {
    if (!isoDate) return "";
    return new Date(`${isoDate}T00:00:00`).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
  }

  function sourceKind(source) {
    if (source.type === "announcement") return `Announcement · ${formatDate(source.published)}`;
    if (source.type === "document") return "ISSS document";
    return "ISSS page";
  }

  function renderSources(sources) {
    const section = element("section", "sources");
    const title = element("h2", "sources-title", "Sources");
    const list = element("ul", "source-list");
    for (const source of sources) {
      const link = element("a", "source");
      link.href = source.url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      const meta = element("span", "source-meta");
      if (source.updates) {
        const badge = element("span", "badge");
        badge.innerHTML = icons.update;
        badge.append("Update");
        badge.title = "A newer announcement about a rule mentioned in this answer";
        meta.append(badge);
      }
      meta.append(element("span", null, sourceKind(source)));
      link.append(element("span", "source-title", source.title), meta);
      const item = element("li");
      item.append(link);
      list.append(item);
    }
    section.setAttribute("aria-label", "Sources");
    section.append(title, list);
    return section;
  }

  function iconButton(icon, label) {
    const button = element("button", "icon-button");
    button.type = "button";
    button.innerHTML = icon;
    button.setAttribute("aria-label", label);
    button.title = label;
    return button;
  }

  async function postFeedback(messageId, rating, comment) {
    const response = await fetch("/api/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message_id: messageId, rating, comment }),
    });
    if (response.status === 401) setSignedIn(false);
    return response.ok;
  }

  function renderFeedback(messageId, rating) {
    const feedback = element("div", "feedback");
    const up = iconButton(icons.thumbsUp, "Helpful");
    const down = iconButton(icons.thumbsDown, "Not helpful");
    const note = element("span", "feedback-note");
    note.setAttribute("role", "status");

    const mark = (value) => {
      up.setAttribute("aria-pressed", String(value === 1));
      down.setAttribute("aria-pressed", String(value === -1));
    };
    const thank = (text) => {
      note.innerHTML = icons.check;
      note.append(text);
    };
    const failed = () => {
      note.textContent = "Couldn't save your feedback. Try again.";
    };

    async function rate(value) {
      mark(value);
      note.textContent = "";
      feedback.querySelector(".feedback-form")?.remove();
      if (!(await postFeedback(messageId, value, null).catch(() => false))) return failed();
      if (value === 1) return thank("Thanks for the feedback");
      const form = element("form", "feedback-form");
      const label = element("label", "visually-hidden", "What was wrong or missing? (optional)");
      const field = element("textarea");
      field.id = `feedback-${messageId}`;
      label.htmlFor = field.id;
      field.rows = 1;
      field.maxLength = 1000;
      field.placeholder = "What was wrong or missing? (optional)";
      const submit = element("button", "button", "Send");
      submit.type = "submit";
      form.append(label, field, submit);
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        submit.disabled = true;
        const saved = await postFeedback(messageId, -1, field.value.trim() || null).catch(() => false);
        if (!saved) {
          submit.disabled = false;
          return failed();
        }
        form.remove();
        thank("Thanks, this helps improve the assistant");
      });
      feedback.append(form);
      field.focus();
    }

    up.addEventListener("click", () => rate(1));
    down.addEventListener("click", () => rate(-1));
    mark(rating);
    feedback.append(element("span", "feedback-label", "Helpful?"), up, down, note);
    return feedback;
  }

  function finishAnswer(view, text, done) {
    if (view.frame) window.cancelAnimationFrame(view.frame);
    view.status.remove();
    view.body.innerHTML = renderMarkdown(text);
    view.item.setAttribute("aria-busy", "false");
    if (done.sources && done.sources.length) view.item.append(renderSources(done.sources));
    const footer = element("div", "message-footer");
    footer.append(renderFeedback(done.message_id, done.rating ?? null));
    if (done.debug) {
      const debug = done.debug;
      footer.append(element("span", "debug", `$${debug.cost_usd.toFixed(4)} · ${debug.output_tokens} tokens · ${debug.search_queries.join(" + ")}`));
    }
    view.item.append(footer);
  }

  function notice(kind, title, message, action) {
    const box = element("div", "notice");
    box.dataset.kind = kind;
    box.setAttribute("role", kind === "info" ? "status" : "alert");
    const icon = element("span", "notice-icon");
    icon.innerHTML = { danger: icons.alert, warning: icons.clock, info: icons.info }[kind];
    const body = element("div", "notice-body");
    body.append(element("strong", "notice-title", title), element("p", null, message));
    if (action) {
      const actions = element("div", "notice-actions");
      const button = element(action.href ? "a" : "button", action.href ? "button button-primary" : "button");
      if (action.href) button.href = action.href;
      else button.type = "button";
      button.innerHTML = action.icon;
      button.append(action.label);
      if (action.run) button.addEventListener("click", action.run);
      actions.append(button);
      body.append(actions);
    }
    box.append(icon, body);
    return box;
  }

  function replaceWithNotice(view, box) {
    if (view.frame) window.cancelAnimationFrame(view.frame);
    view.item.className = "message";
    view.item.removeAttribute("aria-busy");
    view.item.replaceChildren(box);
  }

  function retryAction(question, view, userItem) {
    return {
      label: "Try again",
      icon: icons.retry,
      run: () => {
        view.item.remove();
        userItem.remove();
        ask(question);
      },
    };
  }

  const newChatAction = { label: "Start a new chat", icon: icons.plus, run: () => newChat() };

  function askToLogIn(view, question) {
    writeStorage(window.sessionStorage, PENDING_QUESTION_KEY, question);
    replaceWithNotice(
      view,
      notice(
        "info",
        "Log in to ask questions",
        "The assistant is for Drexel students. Log in or create an account with your Drexel email, and your question will be waiting for you.",
        { label: "Log in", icon: icons.logIn, href: "/login" },
      ),
    );
  }

  function markFull() {
    state.full = true;
    ui.input.disabled = true;
    ui.input.placeholder = "Start a new chat to ask more questions";
    updateComposer();
  }

  function addFullNotice(message) {
    const item = element("li", "message");
    item.append(notice("info", "This chat is full", message, newChatAction));
    ui.thread.append(item);
    markFull();
  }


  async function* readEvents(response) {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) return;
      buffer += decoder.decode(value, { stream: true });
      let boundary;
      while ((boundary = buffer.indexOf("\n\n")) !== -1) {
        const block = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        let name = "message";
        let data = "";
        for (const line of block.split("\n")) {
          if (line.startsWith("event: ")) name = line.slice(7);
          else if (line.startsWith("data: ")) data += line.slice(6);
        }
        yield { name, data: data ? JSON.parse(data) : {} };
      }
    }
  }

  async function errorDetail(response) {
    try {
      const body = await response.json();
      return typeof body.detail === "string" ? body.detail : null;
    } catch {
      return null;
    }
  }

  async function ask(question) {
    if (state.busy || state.full) return;
    setBusy(true);
    showWelcome(false);
    const userItem = addUserMessage(question);
    const view = addAssistantMessage();
    view.item.setAttribute("aria-busy", "true");
    scrollToEnd(true);
    state.followBottom = true;

    if (state.signedIn === false) {
      askToLogIn(view, question);
      setBusy(false);
      return;
    }

    let text = "";
    let finished = false;
    const controller = new AbortController();
    state.controller = controller;
    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ conversation_id: state.conversationId, message: question }),
        signal: controller.signal,
      });
      if (response.status === 401) {
        setSignedIn(false);
        askToLogIn(view, question);
        return;
      }
      if (!response.ok) {
        const detail = await errorDetail(response);
        if (response.status === 429) {
          replaceWithNotice(view, notice("warning", "Question limit reached", detail || "Too many questions for now. Try again later."));
        } else if (response.status === 503 && detail) {
          replaceWithNotice(view, notice("info", "The assistant is resting", detail));
        } else if (response.status === 409) {
          view.item.remove();
          addFullNotice(detail || "Start a new chat to keep going.");
        } else {
          replaceWithNotice(view, notice("danger", "Something went wrong", detail || "The assistant couldn't answer. Please try again.", retryAction(question, view, userItem)));
        }
        return;
      }
      for await (const { name, data } of readEvents(response)) {
        if (name === "meta") {
          setConversation(data.conversation_id);
        } else if (name === "token") {
          text += data.text;
          view.status.hidden = true;
          scheduleRender(view, text);
        } else if (name === "done") {
          finished = true;
          finishAnswer(view, text, data);
          if (data.conversation_full) addFullNotice("You've reached the question limit for one chat. Start a new chat to keep going.");
        } else if (name === "refused") {
          finished = true;
          replaceWithNotice(view, notice("info", "Couldn't answer that", data.message));
        } else if (name === "error") {
          finished = true;
          replaceWithNotice(view, notice("danger", "Something went wrong", data.message, retryAction(question, view, userItem)));
        }
      }
      if (!finished) {
        replaceWithNotice(view, notice("danger", "The answer was interrupted", "Check your connection and try again.", retryAction(question, view, userItem)));
      }
    } catch (error) {
      if (error.name === "AbortError") return;
      replaceWithNotice(view, notice("danger", "Couldn't reach the assistant", "Check your connection and try again.", retryAction(question, view, userItem)));
    } finally {
      if (state.controller === controller) state.controller = null;
      setBusy(false);
      scrollToEnd();
    }
  }

  function newChat() {
    if (state.controller) state.controller.abort();
    state.controller = null;
    setConversation(null);
    state.full = false;
    ui.thread.replaceChildren();
    ui.input.disabled = false;
    ui.input.placeholder = "Ask about CPT, OPT, travel…";
    ui.input.value = "";
    showWelcome(true);
    setBusy(false);
    window.scrollTo({ top: 0 });
    ui.input.focus();
  }

  async function restore() {
    if (!state.conversationId) return;
    try {
      const response = await fetch(`/api/conversations/${encodeURIComponent(state.conversationId)}`);
      if (response.status === 401) {
        setSignedIn(false);
        return;
      }
      if (response.status === 404) {
        setConversation(null);
        return;
      }
      if (!response.ok) return;
      const data = await response.json();
      if (!data.messages.length) return;
      showWelcome(false);
      for (const message of data.messages) {
        if (message.role === "user") {
          addUserMessage(message.text, true);
        } else {
          const view = addAssistantMessage(true);
          finishAnswer(view, message.text, message);
        }
      }
      if (data.conversation_full) addFullNotice("You've reached the question limit for one chat. Start a new chat to keep going.");
      scrollToEnd(true);
    } catch {
      return;
    }
  }


  ui.input.addEventListener("input", updateComposer);
  ui.input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      ui.form.requestSubmit();
    }
  });
  ui.form.addEventListener("submit", (event) => {
    event.preventDefault();
    const question = ui.input.value.trim();
    if (!question || state.busy || state.full) return;
    ui.input.value = "";
    updateComposer();
    ask(question);
  });
  for (const example of ui.examples) {
    example.addEventListener("click", () => ask(example.textContent.trim()));
  }
  ui.newChat.addEventListener("click", () => {
    if (state.conversationId && !window.confirm("Starting a new chat clears this one. You won't be able to come back to it.")) return;
    newChat();
  });


  function setAccountOpen(open) {
    ui.accountButton.setAttribute("aria-expanded", String(open));
    ui.accountPanel.hidden = !open;
  }

  async function showAccount() {
    try {
      const response = await fetch("/api/auth/me");
      if (response.status === 401) setSignedIn(false);
      else if (response.ok) setSignedIn(true, (await response.json()).email);
    } catch {
      return;
    }
  }

  async function logOut() {
    ui.logOut.disabled = true;
    try {
      await fetch("/api/auth/logout", { method: "POST" });
    } finally {
      writeStorage(window.sessionStorage, CONVERSATION_KEY, null);
      window.location.assign("/");
    }
  }

  ui.accountButton.addEventListener("click", () => setAccountOpen(ui.accountPanel.hidden));
  document.addEventListener("click", (event) => {
    if (!ui.accountPanel.hidden && !event.target.closest(".account")) setAccountOpen(false);
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !ui.accountPanel.hidden) {
      setAccountOpen(false);
      ui.accountButton.focus();
    }
  });
  ui.logOut.addEventListener("click", logOut);

  const pendingQuestion = readStorage(window.sessionStorage, PENDING_QUESTION_KEY);
  if (pendingQuestion) {
    writeStorage(window.sessionStorage, PENDING_QUESTION_KEY, null);
    ui.input.value = pendingQuestion;
    ui.input.focus();
  }
  updateComposer();
  showAccount();
  restore();
})();
