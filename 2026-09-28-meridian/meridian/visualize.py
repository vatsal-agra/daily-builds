"""Render a captured cluster trace (see `cli.py trace`) as a self-contained,
dependency-free HTML/Canvas ring visualizer: no build step, no JS
libraries, the JSON payload is embedded directly in the page."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Meridian — Chord ring visualizer</title>
<style>
  :root {
    color-scheme: dark;
    --bg: #0b0e14;
    --panel: #131826;
    --panel-2: #1a2133;
    --border: #26304a;
    --text: #e7ecf7;
    --muted: #8a93ab;
    --accent: #5ec9ff;
    --accent-2: #ff9d5e;
    --good: #58e08a;
    --bad: #ff6b6b;
    --ring: #2c3a5c;
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; background: var(--bg); color: var(--text);
    font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace; }
  body { display: flex; flex-direction: column; height: 100vh; }
  header { padding: 14px 20px; border-bottom: 1px solid var(--border); display: flex;
    align-items: baseline; gap: 14px; flex-wrap: wrap; }
  header h1 { font-size: 16px; margin: 0; font-weight: 600; letter-spacing: 0.02em; }
  header .sub { color: var(--muted); font-size: 12.5px; }
  main { flex: 1; display: flex; min-height: 0; }
  #canvas-wrap { flex: 1; position: relative; display: flex; align-items: center; justify-content: center; }
  canvas { display: block; }
  #sidebar { width: 340px; border-left: 1px solid var(--border); background: var(--panel);
    padding: 16px; overflow-y: auto; font-size: 12.5px; }
  #sidebar h2 { font-size: 12px; text-transform: uppercase; letter-spacing: 0.08em;
    color: var(--muted); margin: 18px 0 8px; }
  #sidebar h2:first-child { margin-top: 0; }
  .kv { display: grid; grid-template-columns: 84px 1fr; gap: 4px 8px; }
  .kv div:nth-child(odd) { color: var(--muted); }
  table.fingers { width: 100%; border-collapse: collapse; font-size: 11.5px; margin-top: 4px; }
  table.fingers th, table.fingers td { text-align: left; padding: 2px 4px; border-bottom: 1px solid var(--border); }
  table.fingers th { color: var(--muted); font-weight: 500; }
  #empty-hint { color: var(--muted); padding: 8px 0; }
  footer { border-top: 1px solid var(--border); padding: 10px 20px; display: flex; gap: 12px;
    align-items: center; background: var(--panel); flex-wrap: wrap; }
  footer label { color: var(--muted); font-size: 12px; }
  select, button { background: var(--panel-2); color: var(--text); border: 1px solid var(--border);
    border-radius: 6px; padding: 6px 10px; font: inherit; cursor: pointer; }
  button:hover, select:hover { border-color: var(--accent); }
  button:disabled { opacity: 0.4; cursor: default; }
  #trace-result { color: var(--muted); font-size: 12.5px; }
  #trace-result b { color: var(--text); }
  .legend { display: flex; gap: 16px; margin-left: auto; color: var(--muted); font-size: 11.5px; }
  .legend span { display: inline-flex; align-items: center; gap: 5px; }
  .dot { width: 9px; height: 9px; border-radius: 50%; display: inline-block; }
</style>
</head>
<body>
<header>
  <h1>Meridian</h1>
  <span class="sub">Chord DHT ring — __NUM_NODES__ nodes, m = __M_BITS__ bits (2^__M_BITS__ ring positions)</span>
</header>
<main>
  <div id="canvas-wrap"><canvas id="ring" width="900" height="900"></canvas></div>
  <div id="sidebar">
    <div id="empty-hint">Click a node on the ring for details.</div>
    <div id="node-detail" style="display:none">
      <h2>Node</h2>
      <div class="kv" id="node-kv"></div>
      <h2>Finger table (click again to hide chords)</h2>
      <table class="fingers"><thead><tr><th>i</th><th>start</th><th>target node</th></tr></thead>
      <tbody id="finger-body"></tbody></table>
    </div>
  </div>
</main>
<footer>
  <label for="trace-select">Lookup trace:</label>
  <select id="trace-select"></select>
  <button id="play-btn">▶ Play</button>
  <button id="reset-btn">⟲ Reset</button>
  <span id="trace-result"></span>
  <div class="legend">
    <span><span class="dot" style="background:var(--accent)"></span>alive</span>
    <span><span class="dot" style="background:var(--bad)"></span>killed</span>
    <span><span class="dot" style="background:var(--accent-2)"></span>active hop</span>
  </div>
</footer>
<script>
const DATA = __DATA_JSON__;

const canvas = document.getElementById('ring');
const ctx = canvas.getContext('2d');
const W = canvas.width, H = canvas.height;
const CX = W / 2, CY = H / 2, R = Math.min(W, H) * 0.36;
const RING_SIZE = Math.pow(2, DATA.m_bits);

const nodesById = new Map(DATA.nodes.map(n => [n.id, n]));
const sortedIds = DATA.nodes.map(n => n.id).sort((a, b) => a - b);

function angleFor(id) { return (id / RING_SIZE) * 2 * Math.PI - Math.PI / 2; }
function pointFor(id) {
  const a = angleFor(id);
  return [CX + R * Math.cos(a), CY + R * Math.sin(a)];
}

let selectedNode = null;
let hopHighlightIndex = -1;  // -1 = none; index into current trace's hops
let currentTraceHops = [];

function draw() {
  ctx.clearRect(0, 0, W, H);

  // base ring
  ctx.strokeStyle = getComputedStyle(document.documentElement).getPropertyValue('--ring');
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.arc(CX, CY, R, 0, 2 * Math.PI);
  ctx.stroke();

  // successor links
  for (const n of DATA.nodes) {
    if (!n.alive || !n.successor_list || !n.successor_list.length) continue;
    const succ = n.successor_list[0];
    if (!nodesById.has(succ.id)) continue;
    drawArc(n.id, succ.id, 'rgba(94,201,255,0.35)', 1.5);
  }

  // finger chords for the selected node
  if (selectedNode && selectedNode.finger_table) {
    selectedNode.finger_table.forEach((f, i) => {
      if (!f || !nodesById.has(f.id) || f.id === selectedNode.id) return;
      drawChord(selectedNode.id, f.id, 'rgba(255,157,94,0.18)', 1);
    });
  }

  // trace path so far
  for (let i = 0; i < hopHighlightIndex; i++) {
    if (i + 1 < currentTraceHops.length) {
      drawChord(currentTraceHops[i], currentTraceHops[i + 1], 'rgba(255,157,94,0.9)', 2.5);
    }
  }

  // nodes
  for (const n of DATA.nodes) {
    const [x, y] = pointFor(n.id);
    const isHot = currentTraceHops[hopHighlightIndex] === n.id;
    ctx.beginPath();
    ctx.arc(x, y, isHot ? 9 : 6, 0, 2 * Math.PI);
    ctx.fillStyle = !n.alive ? '#ff6b6b' : (isHot ? '#ff9d5e' : '#5ec9ff');
    ctx.fill();
    if (selectedNode && selectedNode.id === n.id) {
      ctx.lineWidth = 2;
      ctx.strokeStyle = '#fff';
      ctx.stroke();
    }
    ctx.fillStyle = '#8a93ab';
    ctx.font = '10px ui-monospace, monospace';
    const label = n.id.toString();
    ctx.fillText(label, x + 10, y + 3);
  }
}

function drawArc(fromId, toId, color, width) { drawChord(fromId, toId, color, width, true); }

function drawChord(fromId, toId, color, width, curved) {
  const [x1, y1] = pointFor(fromId);
  const [x2, y2] = pointFor(toId);
  ctx.strokeStyle = color;
  ctx.lineWidth = width;
  ctx.beginPath();
  ctx.moveTo(x1, y1);
  if (curved) {
    ctx.lineTo(x2, y2);
  } else {
    const mx = (x1 + x2) / 2, my = (y1 + y2) / 2;
    const pullX = CX + (mx - CX) * 0.35, pullY = CY + (my - CY) * 0.35;
    ctx.quadraticCurveTo(pullX, pullY, x2, y2);
  }
  ctx.stroke();
}

canvas.addEventListener('click', (ev) => {
  const rect = canvas.getBoundingClientRect();
  const mx = (ev.clientX - rect.left) * (W / rect.width);
  const my = (ev.clientY - rect.top) * (H / rect.height);
  let hit = null, bestDist = 16;
  for (const n of DATA.nodes) {
    const [x, y] = pointFor(n.id);
    const d = Math.hypot(x - mx, y - my);
    if (d < bestDist) { bestDist = d; hit = n; }
  }
  if (hit && selectedNode && hit.id === selectedNode.id) {
    selectedNode = null;
  } else {
    selectedNode = hit;
  }
  renderSidebar();
  draw();
});

function renderSidebar() {
  const empty = document.getElementById('empty-hint');
  const detail = document.getElementById('node-detail');
  if (!selectedNode) { empty.style.display = ''; detail.style.display = 'none'; return; }
  empty.style.display = 'none';
  detail.style.display = '';
  const n = selectedNode;
  document.getElementById('node-kv').innerHTML = `
    <div>id</div><div>${n.id}</div>
    <div>addr</div><div>${n.host}:${n.port}</div>
    <div>status</div><div>${n.alive ? 'alive' : 'KILLED'}</div>
    <div>predecessor</div><div>${n.predecessor ? n.predecessor.id : '(none)'}</div>
    <div>successors</div><div>${(n.successor_list || []).map(s => s.id).join(', ') || '(none)'}</div>
    <div>primary keys</div><div>${n.num_primary_keys}</div>
    <div>replica sets</div><div>${n.num_replica_owners}</div>
  `;
  const body = document.getElementById('finger-body');
  body.innerHTML = '';
  (n.finger_table || []).forEach((f, i) => {
    if (!f) return;
    const start = (n.id + Math.pow(2, i)) % RING_SIZE;
    const tr = document.createElement('tr');
    tr.innerHTML = `<td>${i}</td><td>${start}</td><td>${f.id}</td>`;
    body.appendChild(tr);
  });
}

// --- trace playback -----------------------------------------------------

const traceSelect = document.getElementById('trace-select');
const traceResult = document.getElementById('trace-result');
DATA.traces.forEach((t, i) => {
  const opt = document.createElement('option');
  opt.value = i;
  opt.textContent = t.ok ? `get(${JSON.stringify(t.key)}) -> ${JSON.stringify(t.value)}  [${t.hops.length} hops]`
                          : `get(${JSON.stringify(t.key)}) -> ERROR`;
  traceSelect.appendChild(opt);
});

let playTimer = null;

function loadTrace() {
  stopPlayback();
  const t = DATA.traces[traceSelect.value];
  currentTraceHops = t ? t.hops : [];
  hopHighlightIndex = currentTraceHops.length ? 0 : -1;
  traceResult.innerHTML = t ? (t.ok ? `resolved via ${t.hops.length} hop(s), value = <b>${JSON.stringify(t.value)}</b>` : `error: ${t.error}`) : '';
  draw();
}

function stopPlayback() {
  if (playTimer) { clearInterval(playTimer); playTimer = null; }
  document.getElementById('play-btn').textContent = '▶ Play';
}

document.getElementById('play-btn').addEventListener('click', () => {
  if (playTimer) { stopPlayback(); return; }
  if (!currentTraceHops.length) return;
  hopHighlightIndex = 0;
  document.getElementById('play-btn').textContent = '⏸ Pause';
  playTimer = setInterval(() => {
    hopHighlightIndex++;
    if (hopHighlightIndex >= currentTraceHops.length) { stopPlayback(); hopHighlightIndex = currentTraceHops.length - 1; }
    draw();
  }, 700);
});

document.getElementById('reset-btn').addEventListener('click', () => {
  stopPlayback();
  hopHighlightIndex = currentTraceHops.length ? 0 : -1;
  draw();
});

traceSelect.addEventListener('change', loadTrace);
if (DATA.traces.length) loadTrace();

draw();
renderSidebar();
</script>
</body>
</html>
"""


def render(trace_json_path: str | Path, out_html_path: str | Path) -> None:
    data = json.loads(Path(trace_json_path).read_text())
    payload = json.dumps(data).replace("</", "<\\/")
    html = (
        _TEMPLATE.replace("__DATA_JSON__", payload)
        .replace("__NUM_NODES__", str(len(data.get("nodes", []))))
        .replace("__M_BITS__", str(data.get("m_bits", "?")))
    )
    Path(out_html_path).write_text(html)


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if len(argv) != 2:
        print("usage: python -m meridian.visualize <trace.json> <out.html>", file=sys.stderr)
        return 2
    render(argv[0], argv[1])
    print(f"wrote {argv[1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
