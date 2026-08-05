// app.js — wires the RGA/Site CRDT engine (rga.js) to a live textarea,
// an SSE connection to server.py, and the presence/chaos-panel UI.
//
// The core invariant this file maintains: `editor.value` always equals
// `site.text()` except for the brief window inside a single event handler
// while it's being updated. Local edits are diffed against the textarea's
// previous value (prefix/suffix diff) rather than intercepted at the
// keystroke level, so typing, backspacing, selecting-and-typing, and
// paste/cut all go through one code path.

(function () {
  "use strict";

  const NAME_ADJ = ["Swift", "Quiet", "Amber", "Coral", "Brisk", "Lucid", "Mellow", "Nimble", "Vivid", "Wry"];
  const NAME_NOUN = ["Otter", "Falcon", "Comet", "Maple", "Ember", "Heron", "Willow", "Quokka", "Aspen", "Lynx"];
  const COLORS = ["#e0575b", "#e0964a", "#c9a227", "#5aa855", "#3fa5a0", "#4f8fd6", "#7c6cf0", "#c15fd0"];

  function randomFrom(arr) { return arr[Math.floor(Math.random() * arr.length)]; }

  function getOrCreateIdentity() {
    let siteId = sessionStorage.getItem("braid-site-id");
    let name = sessionStorage.getItem("braid-name");
    let color = sessionStorage.getItem("braid-color");
    if (!siteId) {
      siteId = "s" + Math.random().toString(36).slice(2, 10);
      name = `${randomFrom(NAME_ADJ)} ${randomFrom(NAME_NOUN)}`;
      color = randomFrom(COLORS);
      sessionStorage.setItem("braid-site-id", siteId);
      sessionStorage.setItem("braid-name", name);
      sessionStorage.setItem("braid-color", color);
    }
    return { siteId, name, color };
  }

  const { siteId, name, color } = getOrCreateIdentity();
  const site = new window.BraidRGA.Site(siteId);

  // ---- DOM refs -----------------------------------------------------------

  const editor = document.getElementById("editor");
  const overlay = document.getElementById("cursor-overlay");
  const meDot = document.getElementById("me-dot");
  const meName = document.getElementById("me-name");
  const connStatus = document.getElementById("conn-status");
  const undoBtn = document.getElementById("undo-btn");
  const redoBtn = document.getElementById("redo-btn");
  const offlineBtn = document.getElementById("offline-btn");
  const lagSlider = document.getElementById("lag-slider");
  const lagValue = document.getElementById("lag-value");
  const charCount = document.getElementById("char-count");
  const nodeCount = document.getElementById("node-count");
  const outboxCountEl = document.getElementById("outbox-count");
  const presenceList = document.getElementById("presence-list");
  const eventLog = document.getElementById("event-log");

  meDot.style.background = color;
  meName.textContent = `${name} (you)`;

  // ---- state ------------------------------------------------------------

  let lastKnownText = "";
  let isOffline = false;
  let outbox = [];              // ops queued while offline, flushed on reconnect
  let eventSource = null;
  let presence = new Map();     // siteId -> {name, cursor, color, last_seen}
  let bootstrapped = false;

  // ---- logging -------------------------------------------------------------

  function log(msg, cls) {
    const div = document.createElement("div");
    if (cls) div.className = cls;
    const t = new Date().toLocaleTimeString();
    div.textContent = `${t}  ${msg}`;
    eventLog.appendChild(div);
    while (eventLog.children.length > 200) eventLog.removeChild(eventLog.firstChild);
    eventLog.scrollTop = eventLog.scrollHeight;
  }

  // ---- rendering -------------------------------------------------------------

  function renderStats() {
    const n = site.text().length;
    charCount.textContent = `${n} character${n === 1 ? "" : "s"}`;
    nodeCount.textContent = `${site.doc.sequence.length} node${site.doc.sequence.length === 1 ? "" : "s"} (incl. tombstones)`;
    outboxCountEl.textContent = outbox.length > 0 ? `${outbox.length} op(s) queued offline` : "";
    undoBtn.disabled = !site.canUndo();
    redoBtn.disabled = !site.canRedo();
  }

  function renderPresenceList() {
    presenceList.innerHTML = "";
    const others = [...presence.entries()].filter(([sid]) => sid !== siteId);
    if (others.length === 0) {
      const li = document.createElement("li");
      li.className = "presence-empty";
      li.textContent = "Just you — open another tab to see live sync.";
      presenceList.appendChild(li);
      return;
    }
    for (const [sid, p] of others) {
      const li = document.createElement("li");
      li.className = "presence-item";
      const dot = document.createElement("span");
      dot.className = "dot";
      dot.style.background = p.color;
      dot.style.color = p.color;
      const nm = document.createElement("span");
      nm.className = "name";
      nm.textContent = p.name;
      const pos = document.createElement("span");
      pos.className = "cursor-pos";
      pos.textContent = typeof p.cursor === "number" ? `@${p.cursor}` : "";
      li.append(dot, nm, pos);
      presenceList.appendChild(li);
    }
  }

  // Mirror-div caret measurement: build a hidden clone of the textarea's
  // text box (same font/padding/width) so we can ask the browser "where
  // would character index N land, in pixels?" — the standard technique
  // for overlaying markers on a plain <textarea>.
  let mirror = null;
  function ensureMirror() {
    if (mirror) return mirror;
    mirror = document.createElement("div");
    const cs = getComputedStyle(editor);
    Object.assign(mirror.style, {
      position: "absolute", visibility: "hidden", whiteSpace: "pre-wrap", wordWrap: "break-word",
      top: "0", left: "-9999px",
      font: cs.font, letterSpacing: cs.letterSpacing, padding: cs.padding, border: cs.border,
      width: editor.clientWidth + "px", lineHeight: cs.lineHeight, boxSizing: cs.boxSizing,
    });
    document.body.appendChild(mirror);
    return mirror;
  }

  function caretPixelPosition(index) {
    const m = ensureMirror();
    const text = editor.value;
    m.textContent = "";
    m.appendChild(document.createTextNode(text.slice(0, index)));
    const marker = document.createElement("span");
    marker.textContent = "​";
    m.appendChild(marker);
    m.appendChild(document.createTextNode(text.slice(index)));
    const top = marker.offsetTop - editor.scrollTop;
    const left = marker.offsetLeft - editor.scrollLeft;
    return { top, left };
  }

  function renderCursorOverlay() {
    overlay.innerHTML = "";
    const others = [...presence.entries()].filter(([sid]) => sid !== siteId && typeof presence.get(sid).cursor === "number");
    for (const [sid, p] of others) {
      const idx = Math.max(0, Math.min(p.cursor, site.text().length));
      const { top, left } = caretPixelPosition(idx);
      const caret = document.createElement("div");
      caret.className = "peer-caret";
      caret.style.left = left + "px";
      caret.style.top = top + "px";
      caret.style.height = "1.5em";
      caret.style.background = p.color;
      const tag = document.createElement("span");
      tag.className = "tag";
      tag.textContent = p.name;
      tag.style.background = p.color;
      caret.appendChild(tag);
      overlay.appendChild(caret);
    }
  }

  function renderAll() {
    if (editor.value !== site.text()) {
      const sel = editor.selectionStart;
      editor.value = site.text();
      editor.setSelectionRange(Math.min(sel, editor.value.length), Math.min(sel, editor.value.length));
    }
    lastKnownText = site.text();
    renderStats();
    renderPresenceList();
    renderCursorOverlay();
  }

  // ---- outbound: broadcasting local ops --------------------------------

  function broadcastOp(op) {
    if (isOffline) {
      outbox.push(op);
      renderStats();
      return;
    }
    fetch("/op", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ from: siteId, op }),
    }).catch(() => {
      // fire-and-forget: if this fails transiently, the op is still safe
      // in our own replica; anti-entropy on reconnect isn't implemented
      // for the live UI (that's what crdt/network.py's gossip proves at
      // the algorithm level) — a real deployment would retry/queue here.
    });
  }

  function flushOutbox() {
    if (outbox.length === 0) return;
    log(`reconnecting — flushing ${outbox.length} queued op(s)`, "system");
    const toSend = outbox;
    outbox = [];
    for (const op of toSend) broadcastOp(op);
    renderStats();
  }

  // ---- local editing: diff the textarea against our last known state -----

  function commonPrefixLen(a, b) {
    const n = Math.min(a.length, b.length);
    let i = 0;
    while (i < n && a[i] === b[i]) i++;
    return i;
  }

  function commonSuffixLen(a, b, maxLen) {
    const n = Math.min(a.length, b.length, maxLen);
    let i = 0;
    while (i < n && a[a.length - 1 - i] === b[b.length - 1 - i]) i++;
    return i;
  }

  function handleLocalEdit() {
    const newText = editor.value;
    if (newText === lastKnownText) return;
    const prefix = commonPrefixLen(lastKnownText, newText);
    const maxSuffix = Math.min(lastKnownText.length, newText.length) - prefix;
    const suffix = commonSuffixLen(lastKnownText, newText, maxSuffix);

    const deleteLen = lastKnownText.length - prefix - suffix;
    const insertedStr = newText.slice(prefix, newText.length - suffix);

    let ops = [];
    if (deleteLen > 0) ops = ops.concat(site.typeDeleteRange(prefix, deleteLen));
    if (insertedStr.length > 0) ops = ops.concat(site.typeText(prefix, insertedStr));

    for (const op of ops) broadcastOp(op);
    if (ops.length > 0) {
      log(`you: ${deleteLen ? `deleted ${deleteLen}` : ""}${deleteLen && insertedStr ? ", " : ""}${insertedStr ? `inserted ${JSON.stringify(insertedStr)}` : ""} @ ${prefix}`, "mine");
    }
    lastKnownText = newText;
    renderStats();
    sendPresence();
  }

  // ---- inbound: applying remote ops with cursor tracking -----------------

  function applyRemoteOpTrackingCursor(op, cursorRef) {
    if (op.type === "insert") {
      site.receive(op);
      const idx = site.doc.visibleIndexOfId(op.id);
      if (idx !== -1 && idx <= cursorRef.pos) cursorRef.pos += 1;
    } else if (op.type === "delete") {
      const idx = site.doc.visibleIndexOfId(op.target);
      site.receive(op);
      if (idx !== -1 && idx < cursorRef.pos) cursorRef.pos -= 1;
    } else if (op.type === "restore") {
      site.receive(op);
      const idx = site.doc.visibleIndexOfId(op.target);
      if (idx !== -1 && idx <= cursorRef.pos) cursorRef.pos += 1;
    }
  }

  function applyRemoteOps(ops, fromSite) {
    const cursorRef = { pos: editor.selectionStart };
    const hadFocus = document.activeElement === editor;
    for (const op of ops) applyRemoteOpTrackingCursor(op, cursorRef);
    editor.value = site.text();
    lastKnownText = editor.value;
    if (hadFocus) {
      const p = Math.max(0, Math.min(cursorRef.pos, editor.value.length));
      editor.setSelectionRange(p, p);
    }
    renderStats();
    renderCursorOverlay();
    if (ops.length > 0 && fromSite) {
      log(`${presence.get(fromSite)?.name || fromSite}: ${ops.length} op(s) merged`, "remote");
    }
  }

  // ---- SSE connection ----------------------------------------------------

  function connect() {
    bootstrapped = false;
    eventSource = new EventSource(`/events?site=${encodeURIComponent(siteId)}`);
    connStatus.textContent = "connecting…";
    connStatus.classList.remove("online", "offline");

    eventSource.onopen = () => {
      connStatus.textContent = "live";
      connStatus.classList.add("online");
      connStatus.classList.remove("offline");
    };

    eventSource.onerror = () => {
      if (isOffline) return; // expected — we closed it ourselves
      connStatus.textContent = "reconnecting…";
      connStatus.classList.remove("online");
    };

    eventSource.onmessage = (evt) => {
      const msg = JSON.parse(evt.data);
      if (msg.kind === "bootstrap") {
        for (const op of msg.ops) site.receive(op);
        presence = new Map(Object.entries(msg.presence).map(([sid, p]) => [sid, p]));
        bootstrapped = true;
        renderAll();
        sendPresence();
        log(`synced — ${msg.ops.length} historical op(s) replayed`, "system");
      } else if (msg.kind === "op") {
        if (msg.from === siteId) return; // our own op, already applied locally
        const applyNow = () => applyRemoteOps([msg.op], msg.from);
        const lag = parseInt(lagSlider.value, 10);
        if (lag > 0) setTimeout(applyNow, lag);
        else applyNow();
      } else if (msg.kind === "presence") {
        presence.set(msg.site, { name: msg.name, cursor: msg.cursor, color: msg.color, last_seen: Date.now() });
        renderPresenceList();
        renderCursorOverlay();
      } else if (msg.kind === "presence_leave") {
        if (presence.delete(msg.site)) {
          renderPresenceList();
          renderCursorOverlay();
        }
      }
    };
  }

  function disconnect() {
    if (eventSource) {
      eventSource.close();
      eventSource = null;
    }
  }

  // ---- presence broadcasting (debounced) ----------------------------------

  let presenceTimer = null;
  function sendPresence() {
    if (isOffline) return;
    if (presenceTimer) clearTimeout(presenceTimer);
    presenceTimer = setTimeout(() => {
      fetch("/presence", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ site: siteId, name, cursor: editor.selectionStart, color }),
      }).catch(() => {});
    }, 120);
  }

  // ---- undo / redo -----------------------------------------------------

  function doUndo() {
    const ops = site.undo();
    if (!ops) return;
    for (const op of ops) broadcastOp(op);
    editor.value = site.text();
    lastKnownText = editor.value;
    renderStats();
    renderCursorOverlay();
    log(`you: undo (${ops.length} op(s))`, "mine");
  }

  function doRedo() {
    const ops = site.redo();
    if (!ops) return;
    for (const op of ops) broadcastOp(op);
    editor.value = site.text();
    lastKnownText = editor.value;
    renderStats();
    renderCursorOverlay();
    log(`you: redo (${ops.length} op(s))`, "mine");
  }

  // ---- offline toggle -----------------------------------------------------

  function setOffline(next) {
    isOffline = next;
    offlineBtn.classList.toggle("active", isOffline);
    offlineBtn.textContent = isOffline ? "📡 Go online" : "📡 Go offline";
    if (isOffline) {
      disconnect();
      connStatus.textContent = "offline (editing locally)";
      connStatus.classList.remove("online");
      connStatus.classList.add("offline");
      log("you went offline — local edits will queue", "system");
    } else {
      log("reconnecting…", "system");
      connect();
      flushOutbox();
    }
  }

  // ---- wire up events -----------------------------------------------------

  editor.addEventListener("input", handleLocalEdit);
  editor.addEventListener("keyup", () => { renderCursorOverlay(); sendPresence(); });
  editor.addEventListener("click", () => { renderCursorOverlay(); sendPresence(); });
  editor.addEventListener("scroll", renderCursorOverlay);
  window.addEventListener("resize", renderCursorOverlay);

  editor.addEventListener("keydown", (e) => {
    const mod = e.metaKey || e.ctrlKey;
    if (mod && e.key.toLowerCase() === "z" && !e.shiftKey) {
      e.preventDefault();
      doUndo();
    } else if (mod && ((e.key.toLowerCase() === "z" && e.shiftKey) || e.key.toLowerCase() === "y")) {
      e.preventDefault();
      doRedo();
    }
  });

  undoBtn.addEventListener("click", doUndo);
  redoBtn.addEventListener("click", doRedo);
  offlineBtn.addEventListener("click", () => setOffline(!isOffline));
  lagSlider.addEventListener("input", () => { lagValue.textContent = `${lagSlider.value}ms`; });

  // ---- boot ---------------------------------------------------------------

  connect();
  renderAll();
  setInterval(() => {
    // presence entries silently expire after 20s of no updates (covers
    // ungraceful tab closes the SSE disconnect handler might miss)
    const now = Date.now();
    let changed = false;
    for (const [sid, p] of presence) {
      if (sid !== siteId && now - p.last_seen > 20000) {
        presence.delete(sid);
        changed = true;
      }
    }
    if (changed) { renderPresenceList(); renderCursorOverlay(); }
  }, 5000);
})();
