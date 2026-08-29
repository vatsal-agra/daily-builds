(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const logEl = $("log");
  const statusEl = $("conn-status");
  const roomInput = $("room-input");
  const nameInput = $("name-input");
  const joinBtn = $("join-btn");
  const composer = $("composer");
  const msgInput = $("msg-input");
  const sendBtn = composer.querySelector("button");

  let ws = null;
  let joined = false;
  let myName = null;

  function setStatus(state, label) {
    statusEl.dataset.state = state;
    statusEl.querySelector(".label").textContent = label;
  }

  function appendMsg({ kind, text, meta, mine }) {
    const div = document.createElement("div");
    div.className = "msg" + (kind ? " " + kind : "") + (mine ? " mine" : "");
    const bubble = document.createElement("div");
    bubble.className = "bubble";
    bubble.textContent = text;
    div.appendChild(bubble);
    if (meta) {
      const metaEl = document.createElement("div");
      metaEl.className = "meta";
      metaEl.textContent = meta;
      div.appendChild(metaEl);
    }
    logEl.appendChild(div);
    logEl.scrollTop = logEl.scrollHeight;
  }

  function wsUrl(room) {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    return `${proto}//${location.host}/ws/${encodeURIComponent(room)}`;
  }

  function connect(room) {
    if (ws) {
      try { ws.close(); } catch (e) { /* already closing */ }
    }
    joined = false;
    setStatus("connecting", "connecting…");
    ws = new WebSocket(wsUrl(room));

    ws.onopen = () => setStatus("open", `connected · ${room}`);
    ws.onclose = () => {
      setStatus("closed", "disconnected");
      msgInput.disabled = true;
      sendBtn.disabled = true;
    };
    ws.onerror = () => appendMsg({ kind: "error", text: "connection error" });

    ws.onmessage = (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch (e) {
        appendMsg({ kind: "error", text: "received malformed message from server" });
        return;
      }
      if (msg.type === "welcome") {
        $("stat-members").textContent = msg.members;
      } else if (msg.type === "system") {
        appendMsg({ kind: "system", text: msg.text });
      } else if (msg.type === "chat") {
        const when = new Date(msg.ts * 1000).toLocaleTimeString();
        appendMsg({
          text: msg.text,
          meta: `${msg.from} · ${when}`,
          mine: msg.from === myName,
        });
      } else if (msg.type === "error") {
        appendMsg({ kind: "error", text: msg.error });
      }
    };
  }

  joinBtn.addEventListener("click", () => {
    const room = roomInput.value.trim() || "lobby";
    myName = nameInput.value.trim() || "anon";
    connect(room);
    const doJoin = () => {
      ws.send(JSON.stringify({ type: "join", name: myName }));
      joined = true;
      msgInput.disabled = false;
      sendBtn.disabled = false;
      msgInput.placeholder = "Say something…";
      msgInput.focus();
    };
    if (ws.readyState === WebSocket.OPEN) doJoin();
    else ws.addEventListener("open", doJoin, { once: true });
  });

  composer.addEventListener("submit", (ev) => {
    ev.preventDefault();
    if (!joined || !ws || ws.readyState !== WebSocket.OPEN) return;
    const text = msgInput.value.trim();
    if (!text) return;
    ws.send(JSON.stringify({ type: "chat", text }));
    msgInput.value = "";
  });

  async function pollStatus() {
    try {
      const res = await fetch("/api/status");
      if (!res.ok) return;
      const data = await res.json();
      $("stat-uptime").textContent = `${Math.round(data.uptime_seconds)}s`;
      $("stat-messages").textContent = data.total_messages;
      const room = roomInput.value.trim() || "lobby";
      $("stat-members").textContent = data.rooms[room] || 0;
    } catch (e) { /* server may be mid-restart; ignore and retry next tick */ }
  }
  pollStatus();
  setInterval(pollStatus, 4000);
})();
