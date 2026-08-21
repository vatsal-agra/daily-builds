"use strict";

const PEER_COLORS = ["#e06c75", "#61afef", "#98c379", "#e5c07b", "#c678dd", "#56b6c2"];

function peerColor(peerId) {
  let hash = 0;
  for (let i = 0; i < peerId.length; i++) hash = (hash * 31 + peerId.charCodeAt(i)) >>> 0;
  return PEER_COLORS[hash % PEER_COLORS.length];
}

function randomPeerId() {
  const words = ["fox", "owl", "lynx", "wren", "hare", "moth", "elk", "auk"];
  const w = words[Math.floor(Math.random() * words.length)];
  return `${w}-${Math.random().toString(36).slice(2, 6)}`;
}

function getOrMakePeerId() {
  // Deliberately NOT persisted to sessionStorage: Chrome's "Duplicate Tab"
  // copies sessionStorage verbatim, which would hand two open tabs the
  // SAME peer id while each has its own independently-zeroed Lamport
  // clock -- both tabs' first insert would then mint the identical
  // (1, peerId) node id, and apply_remote's duplicate-delivery check
  // would silently drop the second character. See REVIEW.md #4.
  return randomPeerId();
}

class BraidClient {
  constructor({ room, peerId, onTextChanged, onPresence, onCursor, onStatus }) {
    this.room = room;
    this.peerId = peerId;
    this.doc = new RGA(peerId);
    this.undoManager = new UndoManager(this.doc);
    this.buffer = new CausalDeliveryBuffer((id) => this.doc.hasId(id));
    this.onTextChanged = onTextChanged;
    this.onPresence = onPresence;
    this.onCursor = onCursor;
    this.onStatus = onStatus;
    this.ws = null;
    this.connected = false;
  }

  connect() {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    const url = `${proto}//${location.host}/ws?room=${encodeURIComponent(this.room)}&peer=${encodeURIComponent(this.peerId)}`;
    this.ws = new WebSocket(url);
    this.ws.onopen = () => {
      this.connected = true;
      this.onStatus("connected");
    };
    this.ws.onclose = () => {
      this.connected = false;
      this.onStatus("disconnected — retrying in 1.5s");
      setTimeout(() => this.connect(), 1500);
    };
    this.ws.onerror = () => {};
    this.ws.onmessage = (ev) => this._handleMessage(JSON.parse(ev.data));
  }

  _handleMessage(msg) {
    if (msg.type === "bootstrap") {
      for (const op of msg.ops) this.buffer.submit(op, (o) => this.doc.applyRemote(o));
      this.onTextChanged(this.doc.text());
      this.onPresence(msg.peers || []);
      return;
    }
    if (msg.type === "presence") {
      this.onPresence(msg.peers || []);
      return;
    }
    if (msg.type === "cursor") {
      this.onCursor(msg.peer, msg.after);
      return;
    }
    if (msg.type === "insert" || msg.type === "delete" || msg.type === "undelete") {
      this.buffer.submit(msg, (o) => this.doc.applyRemote(o));
      this.onTextChanged(this.doc.text());
      return;
    }
    if (msg.type === "resync") {
      // Periodic anti-entropy push (REVIEW.md #3): re-applying an
      // already-known op is a no-op (applyRemote/_log are idempotent),
      // so this only ever adds whatever this client is actually missing.
      for (const op of msg.ops) this.buffer.submit(op, (o) => this.doc.applyRemote(o));
      this.onTextChanged(this.doc.text());
      return;
    }
  }

  _send(obj) {
    if (this.ws && this.connected) {
      try {
        this.ws.send(JSON.stringify(obj));
      } catch (e) {
        /* dropped connection, will retry on reconnect */
      }
    }
  }

  localInsert(index, value) {
    const op = this.doc.localInsert(index, value);
    this.undoManager.recordLocalOp(op);
    this._send(op);
  }

  localDelete(index) {
    const op = this.doc.localDelete(index);
    this.undoManager.recordLocalOp(op);
    this._send(op);
  }

  undo() {
    const op = this.undoManager.undo();
    if (op) this._send(op);
    return op;
  }

  redo() {
    const op = this.undoManager.redo();
    if (op) this._send(op);
    return op;
  }

  sendCursor(index) {
    const after = this.doc._visibleIdBefore(index);
    this._send({ type: "cursor", after, deps: after === null ? [] : [after] });
  }

  cursorIndexForNode(afterId) {
    if (afterId === null) return 0;
    const key = idKey(afterId);
    const idx = this.doc.pos.get(key);
    if (idx === undefined) return this.doc.length(); // node fully unknown -> park at end
    // count visible chars up to and including this node (or nearest earlier visible one)
    let count = 0;
    for (let i = 0; i <= idx; i++) {
      const n = this.doc.nodes.get(this.doc.order[i]);
      if (!n.tombstone) count++;
    }
    return count;
  }

  text() {
    return this.doc.text();
  }
}

// ---------------------------------------------------------------------
// diff a textarea's old/new value into a minimal sequence of single-char
// CRDT ops (RGA nodes are one character each) — handles typing, paste,
// cut, and multi-char selection replace, not just single keystrokes.
// ---------------------------------------------------------------------
function diffToOps(oldText, newText) {
  let prefix = 0;
  const maxPrefix = Math.min(oldText.length, newText.length);
  while (prefix < maxPrefix && oldText[prefix] === newText[prefix]) prefix++;
  let oldEnd = oldText.length;
  let newEnd = newText.length;
  while (oldEnd > prefix && newEnd > prefix && oldText[oldEnd - 1] === newText[newEnd - 1]) {
    oldEnd--;
    newEnd--;
  }
  const removedCount = oldEnd - prefix;
  const insertedChars = newText.slice(prefix, newEnd);
  return { deletePos: prefix, deleteCount: removedCount, insertPos: prefix, insertChars: insertedChars };
}

// ---------------------------------------------------------------------
// UI wiring
// ---------------------------------------------------------------------

document.addEventListener("DOMContentLoaded", () => {
  const params = new URLSearchParams(location.search);
  const room = params.get("room") || "default";
  document.getElementById("room-name").textContent = room;
  document.getElementById("room-link").value = location.href;

  const peerId = getOrMakePeerId();
  document.getElementById("peer-id").textContent = peerId;
  document.getElementById("peer-id").style.color = peerColor(peerId);

  const textarea = document.getElementById("editor");
  const statusEl = document.getElementById("status");
  const peersEl = document.getElementById("peers");
  const cursorLayer = document.getElementById("cursor-layer");

  let applyingRemote = false;
  let lastKnownValue = "";
  const remoteCursors = new Map(); // peerId -> afterId

  const client = new BraidClient({
    room,
    peerId,
    onStatus: (s) => (statusEl.textContent = s),
    onPresence: (peers) => {
      peersEl.innerHTML = "";
      for (const p of peers) {
        const chip = document.createElement("span");
        chip.className = "peer-chip";
        chip.textContent = p;
        chip.style.background = peerColor(p);
        peersEl.appendChild(chip);
      }
      // prune ghost carets for peers who are no longer in the room
      // (REVIEW.md #7) -- otherwise a disconnected peer's last-known
      // cursor position renders forever in every other open tab
      const live = new Set(peers);
      for (const p of Array.from(remoteCursors.keys())) {
        if (!live.has(p)) remoteCursors.delete(p);
      }
      renderCursors();
    },
    onCursor: (peer, after) => {
      remoteCursors.set(peer, after);
      renderCursors();
    },
    onTextChanged: (newText) => {
      applyingRemote = true;
      const selStart = textarea.selectionStart;
      const selEnd = textarea.selectionEnd;
      const wasFocused = document.activeElement === textarea;
      // preserve the caret by anchoring to the node just before it,
      // translating back to an index in the *new* text after remote ops land
      const anchor = client.doc._visibleIdBefore(selStart);
      textarea.value = newText;
      if (wasFocused) {
        const newPos = client.cursorIndexForNode(anchor);
        textarea.setSelectionRange(newPos, newPos);
      }
      lastKnownValue = newText;
      applyingRemote = false;
      renderCursors();
    },
  });

  client.connect();

  const undoStatus = document.getElementById("undo-status");
  function refreshUndoStatus() {
    if (!undoStatus) return;
    undoStatus.textContent = `undo: ${client.undoManager.canUndo() ? "available" : "empty"} · redo: ${client.undoManager.canRedo() ? "available" : "empty"}`;
  }

  function applyLocalDocChangeToTextarea() {
    // same anchored-caret preservation as onTextChanged, reused for
    // undo/redo since those mutate the doc without going through the
    // normal input-event diff path
    applyingRemote = true;
    const selStart = textarea.selectionStart;
    const anchor = client.doc._visibleIdBefore(selStart);
    textarea.value = client.text();
    const newPos = client.cursorIndexForNode(anchor);
    textarea.setSelectionRange(newPos, newPos);
    lastKnownValue = client.text();
    applyingRemote = false;
    refreshUndoStatus();
  }

  textarea.addEventListener("keydown", (e) => {
    const mod = e.metaKey || e.ctrlKey;
    if (!mod || e.key.toLowerCase() !== "z") return;
    e.preventDefault();
    if (e.shiftKey) {
      client.redo();
    } else {
      client.undo();
    }
    applyLocalDocChangeToTextarea();
    client.sendCursor(textarea.selectionStart);
  });
  textarea.addEventListener("keydown", (e) => {
    const mod = e.metaKey || e.ctrlKey;
    if (mod && e.key.toLowerCase() === "y") {
      e.preventDefault();
      client.redo();
      applyLocalDocChangeToTextarea();
      client.sendCursor(textarea.selectionStart);
    }
  });

  textarea.addEventListener("input", () => {
    if (applyingRemote) return;
    const newValue = textarea.value;
    const { deletePos, deleteCount, insertPos, insertChars } = diffToOps(lastKnownValue, newValue);
    for (let i = 0; i < deleteCount; i++) client.localDelete(deletePos);
    for (let i = 0; i < insertChars.length; i++) client.localInsert(insertPos + i, insertChars[i]);
    lastKnownValue = client.text();
    if (lastKnownValue !== newValue) {
      // defensive: should never diverge, but never let the visible text
      // silently drift from CRDT state
      textarea.value = lastKnownValue;
    }
    client.sendCursor(textarea.selectionStart);
    refreshUndoStatus();
  });
  refreshUndoStatus();

  let cursorSendTimer = null;
  textarea.addEventListener("keyup", () => scheduleCursorSend());
  textarea.addEventListener("click", () => scheduleCursorSend());
  function scheduleCursorSend() {
    if (cursorSendTimer) clearTimeout(cursorSendTimer);
    cursorSendTimer = setTimeout(() => client.sendCursor(textarea.selectionStart), 60);
  }

  function renderCursors() {
    cursorLayer.innerHTML = "";
    const text = client.text();
    const metrics = measureTextarea(textarea);
    for (const [peer, after] of remoteCursors.entries()) {
      if (peer === peerId) continue;
      const idx = client.cursorIndexForNode(after);
      const pos = caretPixelPosition(textarea, metrics, idx);
      const marker = document.createElement("div");
      marker.className = "remote-caret";
      marker.style.left = pos.left + "px";
      marker.style.top = pos.top + "px";
      marker.style.background = peerColor(peer);
      marker.title = peer;
      const label = document.createElement("div");
      label.className = "remote-caret-label";
      label.textContent = peer;
      label.style.background = peerColor(peer);
      marker.appendChild(label);
      cursorLayer.appendChild(marker);
    }
  }

  function measureTextarea(ta) {
    const style = getComputedStyle(ta);
    return {
      lineHeight: parseFloat(style.lineHeight) || parseFloat(style.fontSize) * 1.2,
      font: style.font,
      paddingLeft: parseFloat(style.paddingLeft),
      paddingTop: parseFloat(style.paddingTop),
    };
  }

  // approximate caret pixel position using a hidden mirror div (monospace
  // font makes this reliable without a full contenteditable rewrite)
  const mirror = document.createElement("div");
  mirror.style.position = "absolute";
  mirror.style.visibility = "hidden";
  mirror.style.whiteSpace = "pre-wrap";
  mirror.style.wordWrap = "break-word";
  document.body.appendChild(mirror);

  function caretPixelPosition(ta, metrics, index) {
    const style = getComputedStyle(ta);
    mirror.style.font = style.font;
    mirror.style.width = ta.clientWidth + "px";
    mirror.style.padding = style.padding;
    mirror.style.boxSizing = style.boxSizing;
    const text = client.text();
    const before = text.slice(0, index);
    mirror.textContent = before;
    const marker = document.createElement("span");
    marker.textContent = "​";
    mirror.appendChild(marker);
    const rect = marker.getBoundingClientRect();
    const taRect = ta.getBoundingClientRect();
    return {
      left: rect.left - taRect.left + ta.scrollLeft,
      top: rect.top - taRect.top + ta.scrollTop,
    };
  }

  // ---- chaos control panel ----
  const chaosForm = document.getElementById("chaos-form");
  chaosForm.addEventListener("submit", (e) => {
    e.preventDefault();
    const loss = document.getElementById("chaos-loss").value;
    const dup = document.getElementById("chaos-dup").value;
    const latMin = document.getElementById("chaos-lat-min").value;
    const latMax = document.getElementById("chaos-lat-max").value;
    fetch(`/api/chaos?room=${encodeURIComponent(room)}&loss=${loss}&dup=${dup}&lat_min=${latMin}&lat_max=${latMax}`)
      .then((r) => r.json())
      .then((s) => (document.getElementById("chaos-status").textContent = JSON.stringify(s)));
  });

  document.getElementById("partition-btn").addEventListener("click", () => {
    fetch(`/api/chaos?room=${encodeURIComponent(room)}&partition=${encodeURIComponent(peerId)}|${encodeURIComponent("__others__")}&ticks=125`)
      .then((r) => r.json())
      .then((s) => (document.getElementById("chaos-status").textContent = "partitioned: " + JSON.stringify(s)));
  });
  document.getElementById("heal-btn").addEventListener("click", () => {
    fetch(`/api/chaos?room=${encodeURIComponent(room)}&heal=1`)
      .then((r) => r.json())
      .then((s) => (document.getElementById("chaos-status").textContent = "healed: " + JSON.stringify(s)));
  });
});
