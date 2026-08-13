// app.js — wires the DOM to the CRDT peers and the simulated network. All
// the interesting logic lives in src/; this file is just plumbing.

import { Peer } from './src/peer.js';
import { Network, RealClock } from './src/network.js';
import { hashText, colorForSite } from './src/attribution.js';

const NAME_POOL = ['Alice', 'Bob', 'Carol', 'Dave', 'Eve', 'Frank', 'Grace', 'Heidi', 'Ivan', 'Judy'];
const GROUP_LABELS = ['A', 'B', 'C', 'D'];
const ALL_GROUP = 'A'; // group label meaning "everyone" right after a heal

const net = new Network({ clock: new RealClock(), minLatency: 150, maxLatency: 900, lossRate: 0 });

/** @type {Map<string, {peer: Peer, group: string, els: any}>} */
const peers = new Map();
let siteOrder = []; // stable color-assignment order
let attributionOn = false;
let logOn = false;

const els = {
  peersGrid: document.getElementById('peersGrid'),
  partitionRow: document.getElementById('partitionRow'),
  convergenceBadge: document.getElementById('convergenceBadge'),
  convergenceLabel: document.getElementById('convergenceLabel'),
  convergenceHashes: document.getElementById('convergenceHashes'),
  logPanel: document.getElementById('logPanel'),
  logPanelWrap: document.getElementById('logPanelWrap'),
  minLatency: document.getElementById('minLatency'),
  maxLatency: document.getElementById('maxLatency'),
  lossRate: document.getElementById('lossRate'),
  minLatencyVal: document.getElementById('minLatencyVal'),
  maxLatencyVal: document.getElementById('maxLatencyVal'),
  lossRateVal: document.getElementById('lossRateVal'),
  healBtn: document.getElementById('healBtn'),
  addPeerBtn: document.getElementById('addPeerBtn'),
  attributionToggle: document.getElementById('attributionToggle'),
  logToggle: document.getElementById('logToggle'),
};

// ---------- network controls ----------

function syncNetworkParamsFromSliders() {
  net.minLatency = Number(els.minLatency.value);
  net.maxLatency = Math.max(net.minLatency, Number(els.maxLatency.value));
  net.lossRate = Number(els.lossRate.value) / 100;
  els.minLatencyVal.textContent = `${net.minLatency}ms`;
  els.maxLatencyVal.textContent = `${net.maxLatency}ms`;
  els.lossRateVal.textContent = `${Math.round(net.lossRate * 100)}%`;
}
[els.minLatency, els.maxLatency, els.lossRate].forEach((el) => el.addEventListener('input', syncNetworkParamsFromSliders));
syncNetworkParamsFromSliders();

els.healBtn.addEventListener('click', () => {
  net.healAll();
  for (const entry of peers.values()) entry.group = ALL_GROUP;
  renderPartitionRow();
  logEvent('— network healed —');
});

els.attributionToggle.addEventListener('click', () => {
  attributionOn = !attributionOn;
  els.attributionToggle.classList.toggle('active', attributionOn);
  for (const entry of peers.values()) {
    entry.els.attribution.classList.toggle('show', attributionOn);
    renderAttribution(entry);
  }
});

els.logToggle.addEventListener('click', () => {
  logOn = !logOn;
  els.logToggle.classList.toggle('active', logOn);
  els.logPanelWrap.style.display = logOn ? '' : 'none';
});

els.addPeerBtn.addEventListener('click', () => addPeer());

// ---------- peer lifecycle ----------

function nextName() {
  for (const n of NAME_POOL) if (!peers.has(n)) return n;
  return `Peer${peers.size + 1}`;
}

function addPeer() {
  const siteId = nextName();
  const peer = new Peer(siteId);

  // Join snapshot: a brand-new replica catches up by replaying every op
  // every EXISTING peer has ever originated. Union of "ops each site
  // originated" is the complete history, and replaying is safe regardless
  // of order (inserts causally-buffer themselves; applying a known op
  // twice is a no-op) — this is exactly how a real client bootstraps off
  // an existing peer's state when it joins a live document.
  for (const { peer: existing } of peers.values()) {
    for (const op of existing.resyncOps()) peer.receive(op);
  }

  siteOrder.push(siteId);
  const cardEls = buildPeerCard(siteId, peer);
  peers.set(siteId, { peer, group: ALL_GROUP, els: cardEls });
  net.addPeer(siteId, (op) => {
    peer.receive(op);
    onRemoteApplied(siteId);
  });
  net.setPartition(siteId, ALL_GROUP);

  renderPartitionRow();
  refreshPeerCard(siteId);
  updateConvergenceBadge();
}

function removePeer(siteId) {
  if (peers.size <= 1) return; // keep at least one peer
  net.removePeer(siteId);
  peers.get(siteId)?.els.card.remove();
  peers.delete(siteId);
  siteOrder = siteOrder.filter((s) => s !== siteId);
  renderPartitionRow();
  updateConvergenceBadge();
}

// ---------- peer card DOM ----------

function buildPeerCard(siteId, peer) {
  const card = document.createElement('div');
  card.className = 'peer-card';
  const color = colorForSite(siteId, siteOrder);
  card.style.setProperty('color', color);

  card.innerHTML = `
    <div class="head">
      <span class="swatch" style="background:${color}"></span>
      <span class="name">${siteId}</span>
      <span class="pending-badge" title="ops buffered, waiting on a causal dependency">buffered</span>
      <span class="group-badge">group A</span>
      <button class="remove-peer-btn" title="remove peer">✕</button>
    </div>
    <textarea spellcheck="false" placeholder="Type here…"></textarea>
    <div class="attribution"></div>
    <div class="toolbar">
      <button class="undo-btn" title="undo this peer's last edit">↶ Undo</button>
      <button class="redo-btn" title="redo">↷ Redo</button>
      <span class="stat hash-stat"></span>
    </div>
  `;

  const textarea = card.querySelector('textarea');
  const attribution = card.querySelector('.attribution');
  const undoBtn = card.querySelector('.undo-btn');
  const redoBtn = card.querySelector('.redo-btn');
  const removeBtn = card.querySelector('.remove-peer-btn');
  const pendingBadge = card.querySelector('.pending-badge');
  const groupBadge = card.querySelector('.group-badge');
  const hashStat = card.querySelector('.hash-stat');

  textarea.addEventListener('input', () => {
    const ops = peer.setText(textarea.value);
    for (const op of ops) net.broadcast(siteId, op);
    logEvent(`${siteId} edited (${ops.length} op${ops.length === 1 ? '' : 's'})`);
    refreshPeerCard(siteId, { skipTextarea: true });
    updateConvergenceBadge();
  });

  undoBtn.addEventListener('click', () => {
    const op = peer.undo();
    if (op) net.broadcast(siteId, op);
    refreshPeerCard(siteId);
    updateConvergenceBadge();
  });
  redoBtn.addEventListener('click', () => {
    const op = peer.redo();
    if (op) net.broadcast(siteId, op);
    refreshPeerCard(siteId);
    updateConvergenceBadge();
  });
  removeBtn.addEventListener('click', () => removePeer(siteId));

  els.peersGrid.appendChild(card);
  return { card, textarea, attribution, undoBtn, redoBtn, pendingBadge, groupBadge, hashStat };
}

function onRemoteApplied(siteId) {
  refreshPeerCard(siteId);
  updateConvergenceBadge();
}

/** Re-render one peer's card from its current doc state. Preserves the
 * user's cursor position in that pane if they're mid-edit elsewhere. */
function refreshPeerCard(siteId, { skipTextarea = false } = {}) {
  const entry = peers.get(siteId);
  if (!entry) return;
  const { peer, els: e } = entry;
  const newText = peer.text;

  if (!skipTextarea && e.textarea.value !== newText) {
    const focused = document.activeElement === e.textarea;
    const selStart = e.textarea.selectionStart;
    const selEnd = e.textarea.selectionEnd;
    const oldText = e.textarea.value;
    e.textarea.value = newText;
    if (focused) {
      const [ns, ne] = adjustSelection(oldText, newText, selStart, selEnd);
      e.textarea.setSelectionRange(ns, ne);
    }
  }

  e.undoBtn.disabled = !peer.canUndo();
  e.redoBtn.disabled = !peer.canRedo();
  e.pendingBadge.classList.toggle('show', !peer.doc.isFullyDelivered());
  e.groupBadge.textContent = `group ${entry.group}`;
  e.hashStat.textContent = `${newText.length} chars · #${hashText(newText)}`;
  renderAttribution(entry);
}

function renderAttribution(entry) {
  if (!attributionOn) return;
  const nodes = entry.peer.doc.visibleNodes();
  const frag = document.createDocumentFragment();
  for (const n of nodes) {
    const span = document.createElement('span');
    span.className = 'ch';
    span.style.background = colorForSite(n.id.site, siteOrder) + '33';
    span.style.color = colorForSite(n.id.site, siteOrder);
    span.title = `written by ${n.id.site}`;
    span.textContent = n.char === ' ' ? ' ' : n.char;
    frag.appendChild(span);
  }
  entry.els.attribution.innerHTML = '';
  entry.els.attribution.appendChild(frag);
}

/** Shift a [start, end] selection across an oldText -> newText edit,
 * using the same prefix/suffix diff peer.setText uses internally, so a
 * remote insert/delete before the cursor moves it, and one after doesn't. */
function adjustSelection(oldText, newText, start, end) {
  let p = 0;
  const maxP = Math.min(oldText.length, newText.length);
  while (p < maxP && oldText[p] === newText[p]) p++;
  let oldEnd = oldText.length;
  let newEnd = newText.length;
  while (oldEnd > p && newEnd > p && oldText[oldEnd - 1] === newText[newEnd - 1]) {
    oldEnd--;
    newEnd--;
  }
  const delta = newEnd - oldEnd; // can be negative
  const shift = (pos) => {
    if (pos <= p) return pos;
    if (pos >= oldEnd) return pos + delta;
    return p + (newEnd - p); // was inside the changed region: snap to its end
  };
  return [clamp(shift(start), 0, newText.length), clamp(shift(end), 0, newText.length)];
}
function clamp(v, lo, hi) {
  return Math.max(lo, Math.min(hi, v));
}

// ---------- partitions ----------

function renderPartitionRow() {
  els.partitionRow.innerHTML = '';
  for (const siteId of siteOrder) {
    const entry = peers.get(siteId);
    if (!entry) continue;
    const chip = document.createElement('div');
    chip.className = 'partition-chip';
    const color = colorForSite(siteId, siteOrder);
    const select = document.createElement('select');
    for (const g of GROUP_LABELS) {
      const opt = document.createElement('option');
      opt.value = g;
      opt.textContent = `group ${g}`;
      if (g === entry.group) opt.selected = true;
      select.appendChild(opt);
    }
    select.addEventListener('change', () => {
      entry.group = select.value;
      net.setPartition(siteId, select.value);
      refreshPeerCard(siteId);
      logEvent(`${siteId} moved to group ${select.value}`);
    });
    chip.innerHTML = `<span class="swatch" style="background:${color}"></span><strong>${siteId}</strong>`;
    chip.appendChild(select);
    els.partitionRow.appendChild(chip);
  }
}

// ---------- convergence + activity log ----------

function updateConvergenceBadge() {
  const texts = [...peers.values()].map((p) => p.peer.text);
  const hashes = texts.map(hashText);
  const converged = new Set(hashes).size <= 1;
  els.convergenceBadge.classList.toggle('diverged', !converged);
  els.convergenceLabel.textContent = converged ? 'all peers in sync' : 'diverged — network split or in flight';
  els.convergenceHashes.textContent = [...peers.keys()].map((id, i) => `${id}:${hashes[i]}`).join('  ');
}

function logEvent(text) {
  if (!els.logPanel) return;
  const line = document.createElement('div');
  line.className = 'entry';
  line.innerHTML = `<span class="t">${new Date().toLocaleTimeString()}</span><span>${text}</span>`;
  els.logPanel.appendChild(line);
  while (els.logPanel.children.length > 300) els.logPanel.removeChild(els.logPanel.firstChild);
}

// mirror low-level network deliveries into the activity log too
setInterval(() => {
  if (!logOn) return;
  const recent = net.log.slice(-40);
  els.logPanel.innerHTML = '';
  for (const e of recent) {
    const line = document.createElement('div');
    line.className = `entry ${e.status}`;
    line.innerHTML = `<span class="t"></span><span>${e.from} → ${e.to}: <span class="status">${e.status}</span> <code>${e.op.type}</code></span>`;
    els.logPanel.appendChild(line);
  }
}, 500);

// periodic anti-entropy: re-announce each peer's own history, so genuine
// packet loss (not just latency/partition) still converges eventually —
// re-applying an already-known op is always a no-op.
setInterval(() => {
  for (const [siteId, entry] of peers) {
    for (const op of entry.peer.resyncOps()) net.broadcast(siteId, op);
  }
}, 4000);

// keep every card's "buffered" badge and hash fresh even with no direct edit
setInterval(() => {
  for (const siteId of peers.keys()) refreshPeerCard(siteId, { skipTextarea: false });
  updateConvergenceBadge();
}, 700);

// ---------- boot ----------

addPeer();
addPeer();
addPeer();
