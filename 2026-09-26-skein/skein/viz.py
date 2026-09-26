"""Generates a self-contained, dependency-free HTML graph visualizer: a
force-directed Canvas layout of the real graph, with an optional SkeinQL
query result highlighted on top of it.
"""
import json

from .storage import Graph
from .query.executor import compute_var_kinds
from .query.parser import parse
from .query.executor import execute


def _graph_payload(graph: Graph) -> dict:
    nodes = [
        {"id": n.id, "labels": sorted(n.labels), "props": n.props}
        for n in graph.nodes.values()
    ]
    edges = [
        {"id": e.id, "type": e.type, "src": e.src, "dst": e.dst, "props": e.props}
        for e in graph.edges.values()
    ]
    return {"nodes": nodes, "edges": edges}


def _query_highlight(graph: Graph, query_text: str):
    """Runs a SkeinQL statement and returns (rows, plan, highlighted_node_ids,
    highlighted_edge_ids) so the visualizer can mark exactly what matched.
    """
    stmt = parse(query_text)
    var_kinds = compute_var_kinds(stmt)
    rows, plan = execute(graph, stmt, explain=True)
    # Re-run the match alone (no mutation risk: execute() already ran the
    # real statement) to recover which concrete ids were touched, by
    # inspecting the match/create patterns' variables against var_kinds.
    from .query.executor import match_pattern

    node_ids, edge_ids = set(), set()
    if stmt.match is not None:
        bindings, _ = match_pattern(graph, stmt.match)
        for binding in bindings:
            for var, vid in binding.items():
                if var.startswith("__pos"):
                    continue
                if var_kinds.get(var) == "edge":
                    edge_ids.add(vid)
                else:
                    node_ids.add(vid)
    return rows, plan, sorted(node_ids), sorted(edge_ids)


def render_html(graph: Graph, query_text: str = None) -> str:
    payload = _graph_payload(graph)
    query_block = None
    if query_text:
        rows, plan, hi_nodes, hi_edges = _query_highlight(graph, query_text)
        query_block = {
            "text": query_text,
            "plan": plan,
            "rows": rows if rows is not None else [],
            "highlightNodes": hi_nodes,
            "highlightEdges": hi_edges,
        }

    def _safe_json(obj) -> str:
        # A node/edge property containing the literal text "</script>"
        # would otherwise close the embedding <script> tag early and let
        # the rest of the page render as raw markup -- the same class of
        # bug this repo's Loom/Concord/Palimpsest builds hit and fixed.
        return json.dumps(obj).replace("</", "<\\/")

    data_json = _safe_json(payload)
    query_json = _safe_json(query_block)

    return _TEMPLATE.replace("__DATA_JSON__", data_json).replace("__QUERY_JSON__", query_json)


_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Skein graph viewer</title>
<style>
  :root {
    --bg: #0f1117; --panel: #181b24; --border: #2a2e3a; --text: #e6e8ee;
    --muted: #8a8f9c; --accent: #6ea8fe; --highlight: #ffb454; --edge: #454a58;
  }
  @media (prefers-color-scheme: light) {
    :root { --bg: #f5f6f8; --panel: #ffffff; --border: #dde1e8; --text: #1b1e26;
             --muted: #5b6270; --accent: #2a63d6; --highlight: #c9701a; --edge: #c3c8d4; }
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--text);
         font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
  #layout { display: flex; flex-direction: row; height: 100vh; }
  #canvas-wrap { flex: 1; position: relative; min-width: 0; }
  canvas { display: block; width: 100%; height: 100%; cursor: grab; }
  #sidebar { width: 320px; flex-shrink: 0; background: var(--panel); border-left: 1px solid var(--border);
             padding: 16px; overflow-y: auto; }
  h1 { font-size: 15px; margin: 0 0 4px; }
  .sub { color: var(--muted); font-size: 12px; margin-bottom: 16px; }
  .card { background: var(--bg); border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px; margin-bottom: 12px; }
  .card h2 { font-size: 12px; text-transform: uppercase; letter-spacing: .04em; color: var(--muted); margin: 0 0 8px; }
  .label { display: inline-block; background: var(--accent); color: #06121f; font-size: 11px; font-weight: 600;
           border-radius: 999px; padding: 1px 8px; margin: 0 4px 4px 0; }
  table { width: 100%; border-collapse: collapse; font-size: 12px; }
  td, th { padding: 3px 4px; text-align: left; border-bottom: 1px solid var(--border); vertical-align: top; word-break: break-word; }
  th { color: var(--muted); font-weight: 500; }
  code { background: var(--bg); border: 1px solid var(--border); border-radius: 4px; padding: 1px 4px; font-size: 11px; }
  #legend { position: absolute; bottom: 12px; left: 12px; font-size: 11px; color: var(--muted); }
  .dot { display: inline-block; width: 9px; height: 9px; border-radius: 50%; margin-right: 4px; vertical-align: middle; }
  #empty { color: var(--muted); font-size: 12px; }
</style>
</head>
<body>
<div id="layout">
  <div id="canvas-wrap">
    <canvas id="cv"></canvas>
    <div id="legend"></div>
  </div>
  <div id="sidebar">
    <h1>Skein graph viewer</h1>
    <div class="sub" id="stats"></div>
    <div id="query-card"></div>
    <div class="card" id="detail"><h2>Selection</h2><div id="detail-body"><div id="empty">Click a node to inspect it.</div></div></div>
  </div>
</div>
<script>
const DATA = __DATA_JSON__;
const QUERY = __QUERY_JSON__;

const nodes = DATA.nodes.map(n => ({...n, x: (Math.random()-0.5)*400, y: (Math.random()-0.5)*400, vx: 0, vy: 0}));
const nodeById = new Map(nodes.map(n => [n.id, n]));
const edges = DATA.edges.filter(e => nodeById.has(e.src) && nodeById.has(e.dst));

document.getElementById('stats').textContent = `${nodes.length} nodes, ${edges.length} edges`;

const highlightNodes = new Set(QUERY ? QUERY.highlightNodes : []);
const highlightEdges = new Set(QUERY ? QUERY.highlightEdges : []);

if (QUERY) {
  const rows = QUERY.rows || [];
  const cols = rows.length ? Object.keys(rows[0]) : [];
  let rowsHtml = '<div id="empty">No rows.</div>';
  if (cols.length) {
    rowsHtml = '<table><thead><tr>' + cols.map(c => `<th>${esc(c)}</th>`).join('') +
      '</tr></thead><tbody>' +
      rows.slice(0, 50).map(r => '<tr>' + cols.map(c => `<td>${esc(fmt(r[c]))}</td>`).join('') + '</tr>').join('') +
      '</tbody></table>';
  }
  document.getElementById('query-card').innerHTML = `
    <div class="card">
      <h2>Query</h2>
      <code>${esc(QUERY.text)}</code>
      <p class="sub" style="margin:8px 0 4px">plan: ${esc(fmt(QUERY.plan))}</p>
      ${rowsHtml}
    </div>`;
}

function esc(s) {
  return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
function fmt(v) {
  if (v === null || v === undefined) return 'null';
  if (typeof v === 'object') return JSON.stringify(v);
  return String(v);
}

// -- force-directed layout: Coulomb repulsion + Hooke spring + damping --
const REPULSION = 2600, SPRING = 0.02, SPRING_LEN = 90, DAMPING = 0.85, CENTER_PULL = 0.002;

function step() {
  for (const a of nodes) {
    let fx = -a.x * CENTER_PULL, fy = -a.y * CENTER_PULL;
    for (const b of nodes) {
      if (a === b) continue;
      let dx = a.x - b.x, dy = a.y - b.y;
      let d2 = dx*dx + dy*dy + 0.01;
      let f = REPULSION / d2;
      let d = Math.sqrt(d2);
      fx += (dx / d) * f;
      fy += (dy / d) * f;
    }
    a.fx = fx; a.fy = fy;
  }
  for (const e of edges) {
    const a = nodeById.get(e.src), b = nodeById.get(e.dst);
    let dx = b.x - a.x, dy = b.y - a.y;
    let d = Math.sqrt(dx*dx + dy*dy) + 0.01;
    let f = (d - SPRING_LEN) * SPRING;
    const ux = dx / d, uy = dy / d;
    a.fx += ux * f; a.fy += uy * f;
    b.fx -= ux * f; b.fy -= uy * f;
  }
  for (const a of nodes) {
    if (a.dragging) continue;
    a.vx = (a.vx + a.fx) * DAMPING;
    a.vy = (a.vy + a.fy) * DAMPING;
    a.x += a.vx;
    a.y += a.vy;
  }
}

const cv = document.getElementById('cv');
const ctx = cv.getContext('2d');
let scale = 1, offX = 0, offY = 0;
let selected = null, dragNode = null, panning = false, panStart = null;

function resize() {
  const wrap = document.getElementById('canvas-wrap');
  cv.width = wrap.clientWidth * devicePixelRatio;
  cv.height = wrap.clientHeight * devicePixelRatio;
}
window.addEventListener('resize', resize);
resize();

const style = getComputedStyle(document.documentElement);
const cAccent = style.getPropertyValue('--accent').trim() || '#6ea8fe';
const cHighlight = style.getPropertyValue('--highlight').trim() || '#ffb454';
const cEdge = style.getPropertyValue('--edge').trim() || '#454a58';
const cText = style.getPropertyValue('--text').trim() || '#e6e8ee';

function draw() {
  ctx.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0);
  ctx.clearRect(0, 0, cv.width, cv.height);
  ctx.save();
  ctx.translate(cv.width / devicePixelRatio / 2 + offX, cv.height / devicePixelRatio / 2 + offY);
  ctx.scale(scale, scale);

  for (const e of edges) {
    const a = nodeById.get(e.src), b = nodeById.get(e.dst);
    ctx.strokeStyle = highlightEdges.has(e.id) ? cHighlight : cEdge;
    ctx.lineWidth = highlightEdges.has(e.id) ? 2.2 : 1;
    ctx.beginPath();
    ctx.moveTo(a.x, a.y);
    ctx.lineTo(b.x, b.y);
    ctx.stroke();
    // arrowhead
    const ang = Math.atan2(b.y - a.y, b.x - a.x);
    const r = 9;
    const ex = b.x - Math.cos(ang) * r, ey = b.y - Math.sin(ang) * r;
    ctx.beginPath();
    ctx.moveTo(ex, ey);
    ctx.lineTo(ex - 6 * Math.cos(ang - 0.4), ey - 6 * Math.sin(ang - 0.4));
    ctx.lineTo(ex - 6 * Math.cos(ang + 0.4), ey - 6 * Math.sin(ang + 0.4));
    ctx.closePath();
    ctx.fillStyle = ctx.strokeStyle;
    ctx.fill();
  }

  for (const n of nodes) {
    const r = 8;
    ctx.beginPath();
    ctx.arc(n.x, n.y, r, 0, Math.PI * 2);
    ctx.fillStyle = highlightNodes.has(n.id) ? cHighlight : cAccent;
    ctx.fill();
    if (n === selected) {
      ctx.lineWidth = 2;
      ctx.strokeStyle = cText;
      ctx.stroke();
    }
    ctx.fillStyle = cText;
    ctx.font = '11px sans-serif';
    const label = (n.props && (n.props.name || n.props.title)) || n.labels[0] || n.id;
    ctx.fillText(String(label), n.x + r + 3, n.y + 4);
  }
  ctx.restore();
}

function loop() {
  step();
  draw();
  requestAnimationFrame(loop);
}
loop();

// -- interaction: drag nodes, pan canvas, click to inspect --
function toWorld(px, py) {
  const rect = cv.getBoundingClientRect();
  const cx = (px - rect.left - rect.width / 2 - offX) / scale;
  const cy = (py - rect.top - rect.height / 2 - offY) / scale;
  return {x: cx, y: cy};
}

function pick(px, py) {
  const {x, y} = toWorld(px, py);
  let best = null, bestD = 14;
  for (const n of nodes) {
    const d = Math.hypot(n.x - x, n.y - y);
    if (d < bestD) { bestD = d; best = n; }
  }
  return best;
}

cv.addEventListener('mousedown', (ev) => {
  const hit = pick(ev.clientX, ev.clientY);
  if (hit) {
    dragNode = hit;
    hit.dragging = true;
    selected = hit;
    showDetail(hit);
  } else {
    panning = true;
    panStart = {x: ev.clientX - offX, y: ev.clientY - offY};
  }
});
window.addEventListener('mousemove', (ev) => {
  if (dragNode) {
    const {x, y} = toWorld(ev.clientX, ev.clientY);
    dragNode.x = x; dragNode.y = y; dragNode.vx = 0; dragNode.vy = 0;
  } else if (panning) {
    offX = ev.clientX - panStart.x;
    offY = ev.clientY - panStart.y;
  }
});
window.addEventListener('mouseup', () => {
  if (dragNode) dragNode.dragging = false;
  dragNode = null;
  panning = false;
});
cv.addEventListener('wheel', (ev) => {
  ev.preventDefault();
  const factor = ev.deltaY < 0 ? 1.1 : 0.9;
  scale = Math.max(0.2, Math.min(4, scale * factor));
}, {passive: false});

function showDetail(n) {
  const labels = (n.labels || []).map(l => `<span class="label">${esc(l)}</span>`).join('');
  const props = Object.entries(n.props || {});
  const propsHtml = props.length
    ? '<table><thead><tr><th>property</th><th>value</th></tr></thead><tbody>' +
      props.map(([k, v]) => `<tr><td>${esc(k)}</td><td>${esc(fmt(v))}</td></tr>`).join('') + '</tbody></table>'
    : '<div id="empty">No properties.</div>';
  const outCount = edges.filter(e => e.src === n.id).length;
  const inCount = edges.filter(e => e.dst === n.id).length;
  document.getElementById('detail-body').innerHTML =
    `<div>${labels || '<span class="sub">(no labels)</span>'}</div>` +
    `<p class="sub">id ${n.id} &middot; ${outCount} out / ${inCount} in</p>` +
    propsHtml;
}

document.getElementById('legend').innerHTML =
  `<span class="dot" style="background:${cAccent}"></span>node` +
  (QUERY ? ` &nbsp; <span class="dot" style="background:${cHighlight}"></span>query match` : '') +
  ` &nbsp; drag to move &middot; scroll to zoom &middot; drag background to pan`;
</script>
</body>
</html>
"""
