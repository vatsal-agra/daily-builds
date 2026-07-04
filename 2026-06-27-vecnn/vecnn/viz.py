"""
Interactive HNSW graph visualizer — generates a self-contained HTML file.

Layout: force-directed via d3-force (bundled inline from CDN blob or
inline JS implementation to avoid network deps).

Features:
  - Layer selector (switch between layer 0, 1, 2, …)
  - Nodes colored by max level (hubs = brighter)
  - Animate a nearest-neighbour search step by step
  - Hover for node id, vector summary, metadata
  - Pan / zoom
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from .hnsw import HNSWIndex


def generate_html(
    index: HNSWIndex,
    query: Optional[np.ndarray] = None,
    query_k: int = 5,
    title: str = "VecNN — HNSW Graph",
    max_nodes: int = 500,
) -> str:
    """
    Build a self-contained HTML string visualizing the HNSW index.

    Parameters
    ----------
    index : HNSWIndex
    query : optional query vector to animate search on
    query_k : k for the animated search
    title : page title
    max_nodes : if more nodes exist, sample this many for visualisation
    """
    # ---- Collect graph data ----
    all_nodes = [n for n in index._nodes.values() if not n.deleted]
    if len(all_nodes) > max_nodes:
        all_nodes = all_nodes[:max_nodes]

    node_ids = {n.id for n in all_nodes}

    # Build per-layer adjacency
    max_layer = max((n.level for n in all_nodes), default=0)
    layers = []
    for lc in range(max_layer + 1):
        layer_nodes = []
        layer_links = []
        seen_edges = set()
        for n in all_nodes:
            if n.level < lc:
                continue
            # project to 2D via first 2 PCA dims (or just first 2 components)
            layer_nodes.append({
                "id": n.id,
                "level": n.level,
                "meta": {k: str(v) for k, v in n.metadata.items()},
                "v0": float(n.vector[0]) if len(n.vector) > 0 else 0.0,
                "v1": float(n.vector[1]) if len(n.vector) > 1 else 0.0,
            })
            if lc < len(n.neighbors):
                for nb_id in n.neighbors[lc]:
                    if nb_id not in node_ids:
                        continue
                    edge_key = (min(n.id, nb_id), max(n.id, nb_id))
                    if edge_key not in seen_edges:
                        seen_edges.add(edge_key)
                        layer_links.append({"source": n.id, "target": nb_id})
        layers.append({"nodes": layer_nodes, "links": layer_links})

    # PCA projection for layout (use first 2 PCs of actual vectors)
    if len(all_nodes) >= 2:
        mat = np.stack([n.vector for n in all_nodes])
        mat_centered = mat - mat.mean(axis=0)
        # Fast 2-component PCA via SVD
        try:
            U, S, Vt = np.linalg.svd(mat_centered, full_matrices=False)
            coords_2d = mat_centered @ Vt[:2].T
        except Exception:
            coords_2d = mat_centered[:, :2]
        # Normalise to [-1, 1]
        mn = coords_2d.min(axis=0)
        mx = coords_2d.max(axis=0)
        rng = mx - mn
        rng[rng == 0] = 1.0
        coords_2d = (coords_2d - mn) / rng * 2 - 1
        coord_map = {n.id: coords_2d[i].tolist() for i, n in enumerate(all_nodes)}
    else:
        coord_map = {n.id: [0.0, 0.0] for n in all_nodes}

    # Embed PCA coords into layer node data
    for layer in layers:
        for node in layer["nodes"]:
            c = coord_map.get(node["id"], [0.0, 0.0])
            node["x"] = c[0]
            node["y"] = c[1]

    # Search animation path
    search_steps = []
    if query is not None and len(all_nodes) > 0:
        search_steps = _trace_search(index, query, query_k)

    # ---- Entry point info ----
    ep_id = index._entry_point

    payload = {
        "title": title,
        "metric": index.metric,
        "dim": index.dim,
        "M": index.M,
        "ef_search": index.ef_search,
        "n_nodes": len(all_nodes),
        "max_layer": max_layer,
        "entry_point": ep_id,
        "layers": layers,
        "search_steps": search_steps,
        "query": query.tolist() if query is not None else None,
        "query_k": query_k,
    }

    return _HTML_TEMPLATE.replace("__PAYLOAD__", json.dumps(payload))


def _trace_search(index: HNSWIndex, query: np.ndarray, k: int) -> List[Dict]:
    """Return a list of step dicts tracing the HNSW search."""
    steps = []
    if index._entry_point is None:
        return steps

    dist_fn = index._dist
    ep_id = index._entry_point
    ep_dist = dist_fn(query, index._nodes[ep_id].vector)

    # Phase 1: greedy descend from max_layer to layer 1
    for lc in range(index._max_layer, 0, -1):
        steps.append({"phase": "descend", "layer": lc, "current": ep_id, "visited": []})
        improved = True
        while improved:
            improved = False
            for nb_id in index._nodes[ep_id].neighbors[lc]:
                if nb_id not in index._nodes or index._nodes[nb_id].deleted:
                    continue
                d = dist_fn(query, index._nodes[nb_id].vector)
                if d < ep_dist:
                    ep_id, ep_dist = nb_id, d
                    improved = True
                    steps.append({
                        "phase": "descend_move",
                        "layer": lc,
                        "current": ep_id,
                        "visited": [],
                    })

    # Phase 2: beam search on layer 0
    visited_list = []
    import heapq
    visited = {ep_id}
    candidates = [(ep_dist, ep_id)]
    W = [(-ep_dist, ep_id)]
    ef = index.ef_search

    while candidates:
        c_dist, c_id = heapq.heappop(candidates)
        f_dist = -W[0][0]
        if c_dist > f_dist:
            break
        visited_list.append(c_id)
        for nb_id in index._nodes[c_id].neighbors[0]:
            if nb_id in visited or nb_id not in index._nodes:
                continue
            visited.add(nb_id)
            if index._nodes[nb_id].deleted:
                continue
            nb_dist = dist_fn(query, index._nodes[nb_id].vector)
            f_dist2 = -W[0][0]
            if nb_dist < f_dist2 or len(W) < ef:
                heapq.heappush(candidates, (nb_dist, nb_id))
                heapq.heappush(W, (-nb_dist, nb_id))
                if len(W) > ef:
                    heapq.heappop(W)

        steps.append({
            "phase": "beam",
            "layer": 0,
            "current": c_id,
            "visited": visited_list.copy(),
            "frontier": [nid for _, nid in W],
        })

    results = sorted((-nd, nid) for nd, nid in W)[:k]
    steps.append({
        "phase": "result",
        "layer": 0,
        "results": [nid for _, nid in results],
    })
    return steps


# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------

_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>VecNN — HNSW Visualizer</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#0f1117;color:#e0e0e0;font-family:'Segoe UI',system-ui,sans-serif;height:100vh;display:flex;flex-direction:column}
#header{padding:12px 20px;background:#1a1d27;border-bottom:1px solid #2a2d3a;display:flex;align-items:center;gap:16px;flex-shrink:0}
#header h1{font-size:1.1rem;font-weight:600;color:#7dd3fc}
.badge{background:#2a2d3a;border-radius:6px;padding:3px 10px;font-size:.75rem;color:#94a3b8}
#controls{padding:10px 20px;background:#141720;border-bottom:1px solid #2a2d3a;display:flex;gap:12px;align-items:center;flex-shrink:0;flex-wrap:wrap}
#controls label{font-size:.8rem;color:#94a3b8}
select,button{background:#1e2130;border:1px solid #3a3d4a;color:#e0e0e0;padding:4px 10px;border-radius:6px;font-size:.8rem;cursor:pointer}
button:hover{background:#2a2d3a}
button.active{background:#3b5bdb;border-color:#4c6ef5}
#canvas-wrap{flex:1;position:relative;overflow:hidden}
canvas{position:absolute;top:0;left:0;width:100%;height:100%}
#tooltip{position:absolute;background:#1e2130;border:1px solid #3a3d4a;border-radius:8px;padding:10px 14px;font-size:.78rem;pointer-events:none;display:none;max-width:260px;line-height:1.6;z-index:10}
#tooltip .t-id{color:#7dd3fc;font-weight:600}
#tooltip .t-level{color:#a78bfa}
#info{position:absolute;bottom:12px;left:16px;font-size:.72rem;color:#475569}
#legend{position:absolute;bottom:12px;right:16px;font-size:.72rem;color:#94a3b8;background:#1a1d27;border:1px solid #2a2d3a;border-radius:6px;padding:8px 12px}
#legend div{display:flex;align-items:center;gap:6px;margin-bottom:3px}
.dot{width:10px;height:10px;border-radius:50%;display:inline-block}
#step-info{padding:8px 20px;background:#1a1d27;border-top:1px solid #2a2d3a;font-size:.78rem;color:#94a3b8;flex-shrink:0;min-height:32px}
</style>
</head>
<body>
<div id="header">
  <h1>&#x1F9E0; VecNN — HNSW Graph</h1>
  <span class="badge" id="b-metric"></span>
  <span class="badge" id="b-dim"></span>
  <span class="badge" id="b-nodes"></span>
  <span class="badge" id="b-layers"></span>
</div>
<div id="controls">
  <label>Layer: <select id="sel-layer"></select></label>
  <label>Node size: <input type="range" id="node-size" min="2" max="12" value="5" style="width:80px"></label>
  <button id="btn-search" style="display:none">&#9654; Animate Search</button>
  <button id="btn-step" style="display:none">Step &#9654;</button>
  <button id="btn-reset-view">Reset View</button>
</div>
<div id="canvas-wrap">
  <canvas id="cv"></canvas>
  <div id="tooltip"></div>
  <div id="info"></div>
  <div id="legend">
    <div><span class="dot" style="background:#3b82f6"></span>Layer 0 node</div>
    <div><span class="dot" style="background:#a78bfa"></span>Hub (level ≥ 1)</div>
    <div><span class="dot" style="background:#f59e0b"></span>Entry point</div>
    <div><span class="dot" style="background:#22c55e"></span>Search result</div>
    <div><span class="dot" style="background:#ef4444"></span>Search frontier</div>
  </div>
</div>
<div id="step-info">Select a layer and click "Animate Search" to watch HNSW navigate to nearest neighbours.</div>

<script>
const DATA = __PAYLOAD__;

// ── State ──────────────────────────────────────────────────────────────────
let currentLayer = 0;
let nodeSize = 5;
let pan = {x: 0, y: 0};
let scale = 1;
let dragging = false, dragStart = null, panStart = null;
let hoveredNode = null;
let searchStep = -1; // -1 = not animating
let animTimer = null;

const canvas = document.getElementById('cv');
const ctx = canvas.getContext('2d');
const tooltip = document.getElementById('tooltip');

// ── Badges ─────────────────────────────────────────────────────────────────
document.getElementById('b-metric').textContent = 'metric: ' + DATA.metric;
document.getElementById('b-dim').textContent = 'dim: ' + DATA.dim;
document.getElementById('b-nodes').textContent = DATA.n_nodes + ' nodes';
document.getElementById('b-layers').textContent = (DATA.max_layer + 1) + ' layers';

// ── Layer selector ─────────────────────────────────────────────────────────
const selLayer = document.getElementById('sel-layer');
for (let l = 0; l <= DATA.max_layer; l++) {
  const o = document.createElement('option');
  o.value = l; o.textContent = 'Layer ' + l + ' (' + DATA.layers[l].nodes.length + ' nodes)';
  selLayer.appendChild(o);
}
selLayer.addEventListener('change', () => {
  currentLayer = parseInt(selLayer.value);
  stopAnim(); render();
});

// Search animation controls
const btnSearch = document.getElementById('btn-search');
const btnStep = document.getElementById('btn-step');
if (DATA.search_steps && DATA.search_steps.length > 0) {
  btnSearch.style.display = '';
  btnStep.style.display = '';
}
btnSearch.addEventListener('click', () => { searchStep = 0; render(); updateStepInfo(); });
btnStep.addEventListener('click', () => {
  if (searchStep >= 0 && searchStep < DATA.search_steps.length - 1) {
    searchStep++; render(); updateStepInfo();
  }
});
document.getElementById('btn-reset-view').addEventListener('click', resetView);

document.getElementById('node-size').addEventListener('input', e => {
  nodeSize = parseInt(e.target.value); render();
});

// ── Canvas resize ──────────────────────────────────────────────────────────
function resize() {
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.parentElement.getBoundingClientRect();
  canvas.width = rect.width * dpr;
  canvas.height = rect.height * dpr;
  canvas.style.width = rect.width + 'px';
  canvas.style.height = rect.height + 'px';
  ctx.scale(dpr, dpr);
  render();
}
window.addEventListener('resize', resize);

// ── Coordinate mapping ────────────────────────────────────────────────────
// PCA coords are in [-1, 1]; map to canvas with pan/zoom
function toScreen(x, y) {
  const W = canvas.width / (window.devicePixelRatio || 1);
  const H = canvas.height / (window.devicePixelRatio || 1);
  const cx = W / 2, cy = H / 2;
  const margin = 60;
  const baseScale = (Math.min(W, H) - 2 * margin) / 2;
  return {
    x: cx + (x * baseScale + pan.x) * scale,
    y: cy + (y * baseScale + pan.y) * scale,
  };
}

function resetView() { pan = {x: 0, y: 0}; scale = 1; render(); }

// ── Render ─────────────────────────────────────────────────────────────────
function render() {
  const W = canvas.width / (window.devicePixelRatio || 1);
  const H = canvas.height / (window.devicePixelRatio || 1);
  ctx.clearRect(0, 0, W, H);

  const layer = DATA.layers[currentLayer];
  if (!layer) return;

  // Build node lookup
  const nodeMap = {};
  for (const n of layer.nodes) nodeMap[n.id] = n;

  // Determine search overlay state
  let searchVisited = new Set(), searchFrontier = new Set(), searchResults = new Set();
  let currentStepNode = null;
  if (searchStep >= 0 && searchStep < DATA.search_steps.length) {
    const step = DATA.search_steps[searchStep];
    if (step.visited) step.visited.forEach(id => searchVisited.add(id));
    if (step.frontier) step.frontier.forEach(id => searchFrontier.add(id));
    if (step.results) step.results.forEach(id => searchResults.add(id));
    if (step.current !== undefined) currentStepNode = step.current;
  }

  // Draw edges first
  ctx.lineWidth = 0.6;
  for (const link of layer.links) {
    const a = nodeMap[link.source], b = nodeMap[link.target];
    if (!a || !b) continue;
    const pa = toScreen(a.x, a.y), pb = toScreen(b.x, b.y);
    ctx.beginPath();
    ctx.moveTo(pa.x, pa.y);
    ctx.lineTo(pb.x, pb.y);
    const bothVisited = searchVisited.has(a.id) && searchVisited.has(b.id);
    ctx.strokeStyle = bothVisited ? 'rgba(59,130,246,0.35)' : 'rgba(100,116,139,0.18)';
    ctx.stroke();
  }

  // Draw nodes
  for (const n of layer.nodes) {
    const p = toScreen(n.x, n.y);
    const r = nodeSize * (n.id === DATA.entry_point ? 1.6 : n.level > 0 ? 1.3 : 1.0);
    ctx.beginPath();
    ctx.arc(p.x, p.y, r * scale, 0, Math.PI * 2);

    let color;
    if (searchResults.has(n.id))        color = '#22c55e';
    else if (n.id === currentStepNode)  color = '#f97316';
    else if (searchFrontier.has(n.id))  color = '#ef4444';
    else if (searchVisited.has(n.id))   color = '#6366f1';
    else if (n.id === DATA.entry_point) color = '#f59e0b';
    else if (n.level > 0)               color = '#a78bfa';
    else                                color = '#3b82f6';

    ctx.fillStyle = color;
    ctx.fill();
    if (n.id === hoveredNode) {
      ctx.strokeStyle = '#fff';
      ctx.lineWidth = 1.5;
      ctx.stroke();
    }
  }

  // Info
  document.getElementById('info').textContent =
    `Layer ${currentLayer} · ${layer.nodes.length} nodes · ${layer.links.length} edges` +
    (searchStep >= 0 ? ` · step ${searchStep+1}/${DATA.search_steps.length}` : '');
}

// ── Step info ──────────────────────────────────────────────────────────────
function updateStepInfo() {
  const el = document.getElementById('step-info');
  if (searchStep < 0 || searchStep >= DATA.search_steps.length) {
    el.textContent = 'Search animation not running.';
    return;
  }
  const s = DATA.search_steps[searchStep];
  if (s.phase === 'descend') el.textContent = `Layer ${s.layer}: greedy descent — at node ${s.current}`;
  else if (s.phase === 'descend_move') el.textContent = `Layer ${s.layer}: moved to node ${s.current} (closer)`;
  else if (s.phase === 'beam') el.textContent = `Layer 0 beam search — expanding node ${s.current}; frontier size ${(s.frontier||[]).length}`;
  else if (s.phase === 'result') el.textContent = `Done! Top-${DATA.query_k} results: ${s.results.join(', ')}`;
}

function stopAnim() { if (animTimer) { clearInterval(animTimer); animTimer = null; } searchStep = -1; }

// ── Mouse interactions ─────────────────────────────────────────────────────
function getNodeAt(ex, ey) {
  const layer = DATA.layers[currentLayer];
  if (!layer) return null;
  for (const n of layer.nodes) {
    const p = toScreen(n.x, n.y);
    const r = nodeSize * (n.level > 0 ? 1.3 : 1.0) * scale;
    const dx = ex - p.x, dy = ey - p.y;
    if (dx*dx + dy*dy <= r*r) return n;
  }
  return null;
}

canvas.addEventListener('mousemove', e => {
  const rect = canvas.getBoundingClientRect();
  const ex = e.clientX - rect.left, ey = e.clientY - rect.top;
  if (dragging && dragStart) {
    pan.x = panStart.x + (ex - dragStart.x) / scale;
    pan.y = panStart.y + (ey - dragStart.y) / scale;
    render(); return;
  }
  const n = getNodeAt(ex, ey);
  if (n) {
    hoveredNode = n.id;
    tooltip.style.display = 'block';
    tooltip.style.left = (ex + 14) + 'px';
    tooltip.style.top = (ey - 10) + 'px';
    let html = `<div class="t-id">Node #${n.id}</div>`;
    html += `<div class="t-level">Level: ${n.level}</div>`;
    if (n.id === DATA.entry_point) html += '<div style="color:#f59e0b">⭐ Entry point</div>';
    const mkeys = Object.keys(n.meta || {});
    if (mkeys.length) {
      html += '<div style="margin-top:4px;color:#64748b">Metadata:</div>';
      for (const k of mkeys) html += `<div>${k}: ${n.meta[k]}</div>`;
    }
    tooltip.innerHTML = html;
    render();
  } else {
    if (hoveredNode !== null) { hoveredNode = null; tooltip.style.display = 'none'; render(); }
  }
});

canvas.addEventListener('mousedown', e => {
  const rect = canvas.getBoundingClientRect();
  dragging = true;
  dragStart = {x: e.clientX - rect.left, y: e.clientY - rect.top};
  panStart = {...pan};
});
canvas.addEventListener('mouseup', () => { dragging = false; dragStart = null; });
canvas.addEventListener('mouseleave', () => { dragging = false; tooltip.style.display = 'none'; });

canvas.addEventListener('wheel', e => {
  e.preventDefault();
  const factor = e.deltaY < 0 ? 1.1 : 0.9;
  scale = Math.max(0.1, Math.min(20, scale * factor));
  render();
}, {passive: false});

// ── Boot ───────────────────────────────────────────────────────────────────
resize();
</script>
</body>
</html>
"""
