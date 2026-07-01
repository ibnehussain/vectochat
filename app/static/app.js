(() => {
  "use strict";

  // ── Session ID ──────────────────────────────────────────────────────────────
  function generateUUID() {
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
      const r = (Math.random() * 16) | 0;
      return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
    });
  }

  let sessionId = localStorage.getItem("chatbot_session_id");
  if (!sessionId) {
    sessionId = generateUUID();
    localStorage.setItem("chatbot_session_id", sessionId);
  }
  document.getElementById("session-label").textContent =
    `Session: ${sessionId.slice(0, 8)}…`;

  // ── DOM refs ────────────────────────────────────────────────────────────────
  const chatContainer = document.getElementById("chat-container");
  const userInput = document.getElementById("user-input");
  const sendBtn = document.getElementById("send-btn");
  const clearBtn = document.getElementById("clear-btn");

  // ── Render helpers ──────────────────────────────────────────────────────────
  function appendBubble(role, htmlContent, sources) {
    const bubble = document.createElement("div");
    bubble.className = `bubble ${role}`;
    bubble.innerHTML = htmlContent;

    if (sources && sources.length > 0) {
      const srcDiv = document.createElement("div");
      srcDiv.className = "sources";
      const labels = sources
        .map((s) => `<code>${s.source}</code>`)
        .join(", ");
      srcDiv.innerHTML = `<span>Sources:</span> ${labels}`;
      bubble.appendChild(srcDiv);
    }

    chatContainer.appendChild(bubble);
    chatContainer.scrollTop = chatContainer.scrollHeight;
    return bubble;
  }

  function appendLoading() {
    const bubble = document.createElement("div");
    bubble.className = "bubble assistant";
    bubble.innerHTML =
      '<span class="loading-dot"></span>' +
      '<span class="loading-dot"></span>' +
      '<span class="loading-dot"></span>';
    chatContainer.appendChild(bubble);
    chatContainer.scrollTop = chatContainer.scrollHeight;
    return bubble;
  }

  function renderMarkdown(text) {
    // marked.parse is synchronous
    return marked.parse(text, { breaks: true });
  }

  // ── Load history on startup ─────────────────────────────────────────────────
  async function loadHistory() {
    try {
      const res = await fetch(`/api/history/${encodeURIComponent(sessionId)}`);
      if (!res.ok) return;
      const data = await res.json();
      for (const msg of data.messages) {
        const html =
          msg.role === "assistant"
            ? renderMarkdown(msg.content)
            : escapeHtml(msg.content);
        appendBubble(msg.role, html);
      }
    } catch (_) {
      // Non-fatal — start fresh
    }
  }

  function escapeHtml(text) {
    return text
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  // ── Send message ────────────────────────────────────────────────────────────
  async function sendMessage() {
    const text = userInput.value.trim();
    if (!text) return;

    userInput.value = "";
    sendBtn.disabled = true;

    appendBubble("user", escapeHtml(text));
    const loadingBubble = appendLoading();

    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, message: text }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        loadingBubble.remove();
        appendBubble("assistant", `<em>Error: ${escapeHtml(err.detail || "Unknown error")}</em>`);
        return;
      }

      const data = await res.json();
      loadingBubble.remove();
      appendBubble("assistant", renderMarkdown(data.reply), data.sources);
    } catch (err) {
      loadingBubble.remove();
      appendBubble("assistant", `<em>Network error: ${escapeHtml(err.message)}</em>`);
    } finally {
      sendBtn.disabled = false;
      userInput.focus();
    }
  }

  // ── Clear conversation ──────────────────────────────────────────────────────
  async function clearConversation() {
    if (!confirm("Clear this conversation?")) return;
    try {
      await fetch(`/api/history/${encodeURIComponent(sessionId)}`, {
        method: "DELETE",
      });
    } catch (_) {
      // Best-effort
    }
    chatContainer.innerHTML = "";
    // Rotate session ID
    sessionId = generateUUID();
    localStorage.setItem("chatbot_session_id", sessionId);
    document.getElementById("session-label").textContent =
      `Session: ${sessionId.slice(0, 8)}…`;
  }

  // ── Event listeners ─────────────────────────────────────────────────────────
  sendBtn.addEventListener("click", sendMessage);
  clearBtn.addEventListener("click", clearConversation);
  userInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });

  // ── Init ────────────────────────────────────────────────────────────────────
  loadHistory();
  userInput.focus();
})();
