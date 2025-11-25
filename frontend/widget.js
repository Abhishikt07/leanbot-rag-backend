// widget.js
// Leanext Chat Widget - Full logic: UI + API calls to FastAPI RAG backend

(function () {
  const DEFAULT_OPTIONS = {
    backendUrl: null,               // e.g. "https://your-backend.onrender.com"
    apiKey: null,                   // optional, better to keep on server
    brandColor: "#0f6ad8",
    showOnLoad: false,
    position: "bottom-right",
    saveConversation: true,
    leadTriggerKeywords: ["pricing", "demo", "consulting"],
    leadScoreThreshold: 5.0,
    debugMode: false,
    suggestedFaqs: [],
    fullFaqs: [],
    cssUrl: "widget.css"            // will be overridden by embed.js if needed
  };

  // ---------- Utility: Toast ----------
  function createToast() {
    const toast = document.createElement("div");
    toast.className = "leanext-toast";
    document.body.appendChild(toast);
    return toast;
  }

  function showToast(toastEl, message, duration = 2500) {
    toastEl.textContent = message;
    toastEl.classList.add("show");
    setTimeout(() => toastEl.classList.remove("show"), duration);
  }

  // ---------- Utility: HTTP ----------
  async function postJSON(url, body, apiKey) {
    const headers = { "Content-Type": "application/json" };
    if (apiKey) {
      headers["X-API-Key"] = apiKey; // if you ever decide to use it
    }
    const res = await fetch(url, {
      method: "POST",
      headers,
      body: JSON.stringify(body),
      credentials: "omit"
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  }

  async function getJSON(url) {
    const res = await fetch(url, { credentials: "omit" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  }

  // ---------- Utility: Misc ----------
  function timestamp() {
    const d = new Date();
    let h = d.getHours();
    const ampm = h >= 12 ? "PM" : "AM";
    h = h % 12 || 12;
    const m = String(d.getMinutes()).padStart(2, "0");
    return `${h}:${m} ${ampm}`;
  }

  function escapeHtml(str) {
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function markdownToHtml(str) {
    const escaped = escapeHtml(str).replace(/\n/g, "<br/>");
    return escaped.replace(
      /\[([^\]]+)\]\((https?:\/\/[^\)]+)\)/g,
      '<a href="$2" target="_blank" rel="noopener">$1</a>'
    );
  }

  // ---------- DOM Construction ----------
  function buildWidgetDOM(options, state) {
    const root = document.createElement("div");
    root.className = "leanext-chat-root";

    // Floating bubble
    const bubble = document.createElement("button");
    bubble.className = "leanext-chat-bubble";
    bubble.setAttribute("aria-label", "Open Leanext chat");
    bubble.innerHTML = `<span class="leanext-chat-bubble-icon">💬</span>`;
    root.appendChild(bubble);

    // Dialog
    const dialog = document.createElement("div");
    dialog.className = "leanext-chat-dialog";
    dialog.style.display = "none";
    dialog.setAttribute("role", "dialog");
    dialog.setAttribute("aria-modal", "true");
    dialog.setAttribute("aria-label", "Leanext Conversational AI");

    // Header
    const header = document.createElement("div");
    header.className = "leanext-chat-header";

    const headerMain = document.createElement("div");
    headerMain.className = "leanext-chat-header-main";
    const title = document.createElement("div");
    title.className = "leanext-chat-title";
    title.textContent = "🗣️ LEANEXT Conversational AI";
    const subtitle = document.createElement("div");
    subtitle.className = "leanext-chat-subtitle";
    subtitle.textContent =
      "Sitemap-driven RAG • Multilingual • Feedback-aware";
    headerMain.appendChild(title);
    headerMain.appendChild(subtitle);

    const headerActions = document.createElement("div");
    headerActions.className = "leanext-chat-header-actions";
    const debugBtn = document.createElement("button");
    debugBtn.className = "leanext-chat-header-btn";
    debugBtn.textContent = "⋯";
    const closeBtn = document.createElement("button");
    closeBtn.className = "leanext-chat-header-btn";
    closeBtn.innerHTML = "✕";
    headerActions.appendChild(debugBtn);
    headerActions.appendChild(closeBtn);

    header.appendChild(headerMain);
    header.appendChild(headerActions);

    // Messages area
    const messagesEl = document.createElement("div");
    messagesEl.className = "leanext-chat-messages";
    messagesEl.setAttribute("aria-live", "polite");

    // Debug panel
    const debugPanel = document.createElement("div");
    debugPanel.className = "leanext-debug-panel";
    debugPanel.style.display = "none";

    // Composer
    const composer = document.createElement("div");
    composer.className = "leanext-chat-composer";

    const inputRow = document.createElement("div");
    inputRow.className = "leanext-chat-input-row";

    const textarea = document.createElement("textarea");
    textarea.rows = 1;
    textarea.placeholder =
      "Ask about services or just say ‘hello’… (English, Hindi, Marathi, Kannada, Bengali)";
    textarea.autocomplete = "off";

    const sendBtn = document.createElement("button");
    sendBtn.className = "leanext-chat-send-btn";
    sendBtn.textContent = "Send ⬆️";

    inputRow.appendChild(textarea);
    inputRow.appendChild(sendBtn);

    // FAQ section
    const faqSection = document.createElement("div");
    faqSection.className = "leanext-faq-section";

    const faqTitle = document.createElement("div");
    faqTitle.className = "leanext-faq-title";
    faqTitle.textContent = "💬 Popular Questions";

    const faqGrid = document.createElement("div");
    faqGrid.className = "leanext-faq-grid";

    (options.suggestedFaqs || []).slice(0, 6).forEach((faqText) => {
      const btn = document.createElement("button");
      btn.className = "leanext-faq-btn";
      btn.textContent = faqText;
      btn.addEventListener("click", () => {
        textarea.value = faqText;
        sendMessage(state, options, messagesEl, textarea, toast);
      });
      faqGrid.appendChild(btn);
    });

    const faqMore = document.createElement("div");
    faqMore.className = "leanext-faq-more";
    if ((options.fullFaqs || []).length > 0) {
      faqMore.textContent = `📚 Explore full FAQ library (${options.fullFaqs.length})`;
      faqMore.addEventListener("click", () => {
        const list = options.fullFaqs
          .map((q, i) => `${i + 1}. ${q}`)
          .slice(0, 100)
          .join("\n");
        alert("FAQ Library:\n\n" + list);
      });
    } else {
      faqMore.style.display = "none";
    }

    faqSection.appendChild(faqTitle);
    faqSection.appendChild(faqGrid);
    faqSection.appendChild(faqMore);

    composer.appendChild(inputRow);
    composer.appendChild(faqSection);

    dialog.appendChild(header);
    dialog.appendChild(messagesEl);
    dialog.appendChild(debugPanel);
    dialog.appendChild(composer);

    root.appendChild(dialog);

    // Lead overlay
    const leadOverlay = document.createElement("div");
    leadOverlay.className = "leanext-lead-overlay";
    leadOverlay.style.display = "none";
    const leadModal = document.createElement("div");
    leadModal.className = "leanext-lead-modal";
    leadModal.innerHTML = `
      <h3>🚀 Ready to Consult?</h3>
      <p>We noticed your question is highly relevant to our core services. Share your details & our consultant will contact you.</p>
      <div class="leanext-lead-field">
        <label>Your Name * (Mandatory)</label>
        <input type="text" data-lead-name />
      </div>
      <div class="leanext-lead-field">
        <label>Contact Number (10 digits)</label>
        <input type="tel" maxlength="10" data-lead-number />
      </div>
      <div class="leanext-lead-field">
        <label>Email</label>
        <input type="email" data-lead-email />
      </div>
      <div class="leanext-lead-field">
        <label>Organization Name (Optional)</label>
        <input type="text" data-lead-org />
      </div>
      <div class="leanext-lead-field">
        <label>Select Demo Type (Optional)</label>
        <select data-lead-demo-type>
          <option>General Inquiry</option>
          <option>ERP</option>
          <option>Enterprise LMS</option>
          <option>IMS Software</option>
          <option>Asset & Maintenance Management Software</option>
        </select>
      </div>
      <div class="leanext-lead-field" data-lead-error style="color:#c62828;font-size:11px;"></div>
      <div class="leanext-lead-actions">
        <button class="leanext-btn-primary" data-lead-submit>Submit & Connect</button>
        <button class="leanext-btn-secondary" data-lead-close>No, thanks</button>
      </div>
    `;
    leadOverlay.appendChild(leadModal);
    dialog.appendChild(leadOverlay);

    const toast = createToast();

    // Wire events
    bubble.addEventListener("click", () => {
      toggleDialog(dialog, state);
    });

    closeBtn.addEventListener("click", () => {
      dialog.style.display = "none";
      state.isOpen = false;
    });

    debugBtn.addEventListener("click", async () => {
      if (!options.debugMode || !options.backendUrl) {
        showToast(toast, "Debug mode disabled or backend not set.");
        return;
      }
      debugPanel.style.display =
        debugPanel.style.display === "none" ? "block" : "none";
      if (debugPanel.style.display === "block") {
        await loadDebugInfo(options, debugPanel);
      }
    });

    sendBtn.addEventListener("click", () => {
      sendMessage(state, options, messagesEl, textarea, toast);
    });

    textarea.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        sendMessage(state, options, messagesEl, textarea, toast);
      } else if (e.key === "Escape") {
        dialog.style.display = "none";
        state.isOpen = false;
      }
    });

    // Lead form handlers
    const leadSubmitBtn = leadModal.querySelector("[data-lead-submit]");
    const leadCloseBtn = leadModal.querySelector("[data-lead-close]");
    const leadErrorEl = leadModal.querySelector("[data-lead-error]");

    leadSubmitBtn.addEventListener("click", async () => {
      leadErrorEl.textContent = "";
      const name = leadModal.querySelector("[data-lead-name]").value.trim();
      const number = leadModal
        .querySelector("[data-lead-number]")
        .value.trim();
      const email = leadModal.querySelector("[data-lead-email]").value.trim();
      const org = leadModal.querySelector("[data-lead-org]").value.trim();
      const demoType = leadModal
        .querySelector("[data-lead-demo-type]")
        .value.trim();

      const err = validateLead(name, number, email);
      if (err) {
        leadErrorEl.textContent = err;
        return;
      }

      try {
        await postJSON(options.backendUrl + "/lead", {
          name,
          number: number || null,
          email: email || null,
          demo_type: demoType,
          org: org || null
        }, options.apiKey);
        state.leadLogged = true;
        leadOverlay.style.display = "none";
        showToast(toast, "✅ Lead captured! A consultant will contact you.");
      } catch (e) {
        console.error(e);
        leadErrorEl.textContent = "Database Error: Could not save lead.";
      }
    });

    leadCloseBtn.addEventListener("click", () => {
      leadOverlay.style.display = "none";
      state.showLeadForm = false;
    });

    state.dom = {
      root,
      bubble,
      dialog,
      messagesEl,
      textarea,
      debugPanel,
      leadOverlay,
      toast
    };

    // Initial greeting like Streamlit
    appendAssistantMessage(
      state,
      messagesEl,
      "🌞 Good morning! I'm LeanBot, your AI assistant from Leanext Consulting. How can I help you today?",
      { source: "System", language: "en", distance: null }
    );

    // Restore conversation if enabled
    if (options.saveConversation) {
      restoreConversation(state, messagesEl);
    }

    return root;
  }

  // ---------- Core UI + API Logic ----------

  function toggleDialog(dialog, state) {
    if (dialog.style.display === "none") {
      dialog.style.display = "flex";
      state.isOpen = true;
    } else {
      dialog.style.display = "none";
      state.isOpen = false;
    }
  }

  function validateLead(name, number, email) {
    if (!name) return "Name is mandatory.";
    if (!number && !email)
      return "Provide either a contact number or an email.";
    if (number && !/^\d{10}$/.test(number))
      return "Contact Number must be exactly 10 digits.";
    if (email && !/[^@]+@[^@]+\.[^@]+/.test(email))
      return "Invalid email format (must contain @ and .).";
    return null;
  }

  async function loadDebugInfo(options, debugPanel) {
    debugPanel.textContent = "Loading debug info...";
    try {
      const data = await getJSON(options.backendUrl + "/debug/indexed");
      debugPanel.textContent = "";
      const title = document.createElement("div");
      title.textContent = `Indexed URLs (${data.urls?.length || 0})`;
      debugPanel.appendChild(title);
      (data.urls || []).slice(0, 10).forEach((url, i) => {
        const item = document.createElement("div");
        item.textContent = `${i + 1}. ${url}`;
        debugPanel.appendChild(item);
      });
    } catch (e) {
      debugPanel.textContent = "Failed to load debug info.";
      console.error(e);
    }
  }

  function getHistoryForBackend(state, numTurns = 3) {
    const historyQueries = state.messages
      .filter((m) => m.role === "user")
      .map((m) => m.text);
    return historyQueries.slice(-numTurns);
  }

  function appendUserMessage(state, messagesEl, text) {
    const row = document.createElement("div");
    row.className = "leanext-chat-message-row user";
    const bubble = document.createElement("div");
    bubble.className = "leanext-chat-message user";
    bubble.innerHTML = `<div>${escapeHtml(text)}</div><div class="leanext-chat-message-meta">${timestamp()}</div>`;
    row.appendChild(bubble);
    messagesEl.appendChild(row);
    messagesEl.scrollTop = messagesEl.scrollHeight;

    state.messages.push({ role: "user", text, timestamp: timestamp() });
  }

  function appendAssistantMessage(state, messagesEl, text, meta, indexOverride) {
    const row = document.createElement("div");
    row.className = "leanext-chat-message-row assistant";

    const container = document.createElement("div");
    container.className = "leanext-chat-message assistant";

    const content = document.createElement("div");
    content.innerHTML = markdownToHtml(text);

    const metaEl = document.createElement("div");
    metaEl.className = "leanext-chat-message-meta";
    const lang = (meta.language || "en").toUpperCase();
    const src = meta.source || "Unknown";
    const dist =
      meta.distance != null ? ` | Dist: ${meta.distance.toFixed(4)}` : "";
    metaEl.textContent = `Source: ${src} | Lang: ${lang}${dist}`;

    const feedbackRow = document.createElement("div");
    feedbackRow.className = "leanext-feedback-row";

    if (!src.startsWith("Small Talk")) {
      const upBtn = document.createElement("button");
      upBtn.className = "leanext-feedback-btn";
      upBtn.textContent = "👍";

      const downBtn = document.createElement("button");
      downBtn.className = "leanext-feedback-btn";
      downBtn.textContent = "👎";

      feedbackRow.appendChild(upBtn);
      feedbackRow.appendChild(downBtn);

      const msgIndex =
        typeof indexOverride === "number"
          ? indexOverride
          : state.messages.length;

      upBtn.addEventListener("click", () =>
        handleFeedback(state, msgIndex, "like", upBtn, downBtn)
      );
      downBtn.addEventListener("click", () =>
        handleFeedback(state, msgIndex, "dislike", upBtn, downBtn)
      );
    }

    container.appendChild(content);
    container.appendChild(metaEl);
    container.appendChild(feedbackRow);
    row.appendChild(container);
    messagesEl.appendChild(row);
    messagesEl.scrollTop = messagesEl.scrollHeight;

    const msgData = {
      role: "assistant",
      text,
      meta,
      timestamp: timestamp()
    };

    if (typeof indexOverride === "number") {
      state.messages[indexOverride] = msgData;
    } else {
      state.messages.push(msgData);
    }
  }

  async function handleFeedback(state, msgIndex, type, upBtn, downBtn) {
    const msg = state.messages[msgIndex];
    const userMsg = state.messages[msgIndex - 1];
    if (!msg || !userMsg || !state.options.backendUrl) return;

    if (type === "like") {
      upBtn.classList.add("active");
      downBtn.classList.remove("active");
    } else {
      downBtn.classList.add("active");
      upBtn.classList.remove("active");
    }

    const rating = type === "like" ? 1 : 0;

    try {
      await postJSON(state.options.backendUrl + "/feedback", {
        query: userMsg.text,
        translated_query: userMsg.text, // backend is free to re-translate
        answer: msg.text,
        source: msg.meta?.source || "Unknown",
        language: msg.meta?.language || "en",
        rating
      }, state.options.apiKey);
    } catch (e) {
      console.error("Feedback failed", e);
    }

    if (type === "dislike") {
      await regenerateAnswer(state, msgIndex);
    }
  }

  async function regenerateAnswer(state, msgIndex) {
    const { backendUrl, apiKey } = state.options;
    if (!backendUrl) return;

    const userMsg = state.messages[msgIndex - 1];
    const cleanedQuestion = userMsg.text;
    const history = getHistoryForBackend(state, 3);

    try {
      const resp = await postJSON(backendUrl + "/regenerate", {
        query: cleanedQuestion,
        history
      }, apiKey);

      const newText =
        resp.answer || "Sorry, I couldn't regenerate an answer.";
      const meta = {
        source: resp.source || "Regenerate",
        distance: resp.distance ?? null,
        language: resp.detected_lang || "en"
      };

      appendAssistantMessage(
        state,
        state.dom.messagesEl,
        newText,
        meta,
        msgIndex
      );

      const leadRaw = resp.lead_score ?? 0;
      const leadScoreVal = parseFloat(leadRaw) || 0;
      state.leadScore += leadScoreVal;
      maybeTriggerLeadForm(state);
    } catch (e) {
      console.error("Regeneration failed", e);
    }
  }

  function maybeTriggerLeadForm(state) {
    if (
      !state.leadLogged &&
      state.leadScore >= state.options.leadScoreThreshold
    ) {
      state.dom.leadOverlay.style.display = "flex";
      state.showLeadForm = true;
    }
  }

  async function sendMessage(state, options, messagesEl, textarea, toast) {
    const text = textarea.value.trim();
    if (!text || !options.backendUrl) return;
    textarea.value = "";

    const lowered = text.toLowerCase();
    if (
      !state.leadLogged &&
      options.leadTriggerKeywords.some((k) => lowered.includes(k))
    ) {
      state.dom.leadOverlay.style.display = "flex";
      state.showLeadForm = true;
    }

    appendUserMessage(state, messagesEl, text);

    const thinkingMeta = {
      source: "System",
      language: "en",
      distance: null
    };
    appendAssistantMessage(
      state,
      messagesEl,
      "Assistant is thinking… ✍️",
      thinkingMeta
    );
    const assistantIndex = state.messages.length - 1;

    try {
      const history = getHistoryForBackend(state, 3);
      const resp = await postJSON(options.backendUrl + "/chat", {
        query: text,
        history
      }, options.apiKey);

      let finalText = resp.answer || "Sorry, I couldn't find an answer.";
      const meta = {
        source: resp.source || "Unknown",
        distance: resp.distance ?? null,
        language: resp.detected_lang || "en"
      };

      // Replace thinking message
      appendAssistantMessage(
        state,
        messagesEl,
        finalText,
        meta,
        assistantIndex
      );

      if (resp.related_page && resp.related_page.title && resp.related_page.url) {
        finalText +=
          `\n\n---\n\n🔗 <strong>Related Page:</strong> ` +
          `<a href="${resp.related_page.url}" target="_blank" rel="noopener">${escapeHtml(
            resp.related_page.title
          )}</a>`;
        appendAssistantMessage(
          state,
          messagesEl,
          finalText,
          meta,
          assistantIndex
        );
      }

      const leadRaw = resp.lead_score ?? 0;
      const leadScoreVal = parseFloat(leadRaw) || 0;
      state.leadScore += leadScoreVal;
      maybeTriggerLeadForm(state);

      if (options.saveConversation) {
        persistConversation(state);
      }
    } catch (e) {
      console.error(e);
      showToast(toast, "Error contacting chatbot backend.");
    }
  }

  function persistConversation(state) {
    const key = "leanext_chat_" + location.host;
    const data = {
      ts: Date.now(),
      messages: state.messages,
      leadScore: state.leadScore,
      leadLogged: state.leadLogged
    };
    try {
      localStorage.setItem(key, JSON.stringify(data));
    } catch (e) {
      console.warn("Failed to persist conversation", e);
    }
  }

  function restoreConversation(state, messagesEl) {
    const key = "leanext_chat_" + location.host;
    try {
      const raw = localStorage.getItem(key);
      if (!raw) return;
      const data = JSON.parse(raw);
      const ageMs = Date.now() - data.ts;
      const days = ageMs / (1000 * 60 * 60 * 24);
      if (days > 30) return;

      state.messages = [];
      state.leadScore = data.leadScore || 0;
      state.leadLogged = data.leadLogged || false;

      (data.messages || []).forEach((m) => {
        if (m.role === "assistant") {
          appendAssistantMessage(
            state,
            messagesEl,
            m.text,
            m.meta || { source: "Unknown", language: "en", distance: null }
          );
        } else {
          appendUserMessage(state, messagesEl, m.text);
        }
      });
    } catch (e) {
      console.warn("Failed to restore conversation", e);
    }
  }

  // ---------- PUBLIC API ----------
  window.LeanextChatWidget = {
    init(userOptions = {}) {
      const options = { ...DEFAULT_OPTIONS, ...userOptions };
      const state = {
        options,
        messages: [],
        leadScore: 0,
        leadLogged: false,
        showLeadForm: false,
        isOpen: false,
        dom: {}
      };

      // Brand color
      document.documentElement.style.setProperty(
        "--leanext-brand-color",
        options.brandColor
      );

      // Inject CSS (if not already)
      if (!document.querySelector('link[data-leanext-widget-css]')) {
        const link = document.createElement("link");
        link.rel = "stylesheet";
        link.href = options.cssUrl || "widget.css";
        link.setAttribute("data-leanext-widget-css", "1");
        document.head.appendChild(link);
      }

      const root = buildWidgetDOM(options, state);
      document.body.appendChild(root);

      if (options.showOnLoad) {
        state.dom.dialog.style.display = "flex";
        state.isOpen = true;
      }

      return state;
    }
  };
})();
