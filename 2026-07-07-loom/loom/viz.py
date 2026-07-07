"""Renders a self-contained interactive HTML visualizer for a trained Loom
checkpoint: per-head causal attention heatmaps for a live prompt, the real
training loss/perplexity curve, and a from-scratch PCA projection of the
learned token embedding table."""
import json
import os

import numpy as np

from .pca import pca_2d
from .train import load_checkpoint


def _token_labels(tok, ids):
    return [tok.decode([i]) for i in ids]


def _collect_attention(model, tok, prompt):
    ids = tok.encode(prompt)[: model.block_size]
    if not ids:
        ids = tok.encode("the")[: model.block_size]
    x = np.array(ids, dtype=np.int64).reshape(1, -1)
    model(x)  # populates attn.last_attn on every block as a side effect
    layers = []
    for block in model.blocks:
        layers.append(block.attn.last_attn[0].tolist())  # (n_head, T, T)
    return ids, layers


def render_visualizer(checkpoint_dir, out_path, prompt="ROMEO:"):
    model, tok, config = load_checkpoint(checkpoint_dir)

    token_ids, attn_layers = _collect_attention(model, tok, prompt)
    token_labels = _token_labels(tok, token_ids)

    history_path = os.path.join(checkpoint_dir, "history.json")
    history = {"step": [], "train_loss": [], "val_loss": []}
    if os.path.exists(history_path):
        with open(history_path) as f:
            history = json.load(f)

    emb = model.tok_emb.weight.data
    coords = pca_2d(emb)
    vocab_labels = [tok.decode([i]) for i in range(tok.vocab_size)]
    embedding_points = [
        {"x": float(coords[i, 0]), "y": float(coords[i, 1]), "label": vocab_labels[i]}
        for i in range(tok.vocab_size)
    ]

    data = {
        "prompt": prompt,
        "tokenLabels": token_labels,
        "attnLayers": attn_layers,   # [layer][head][i][j]
        "nLayer": config["n_layer"],
        "nHead": config["n_head"],
        "history": history,
        "embeddingPoints": embedding_points,
        "vocabSize": tok.vocab_size,
    }

    # Corpus-derived token labels could themselves contain "</script>" - guard
    # against that breaking out of the inline <script> block.
    safe_json = json.dumps(data).replace("</", "<\\/")
    html = _TEMPLATE.replace("__LOOM_DATA__", safe_json)
    with open(out_path, "w") as f:
        f.write(html)


_TEMPLATE = r"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Loom - model introspection</title>
<style>
  :root {
    --surface-1: #fcfcfb; --page: #f9f9f7; --text-primary: #0b0b0b;
    --text-secondary: #52514e; --muted: #898781; --grid: #e1e0d9;
    --baseline: #c3c2b7; --series-1: #2a78d6; --series-2: #1baf7a;
    --border: rgba(11,11,11,0.10);
    --seq-100: #cde2fb; --seq-250: #86b6ef; --seq-450: #2a78d6; --seq-650: #104281;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --surface-1: #1a1a19; --page: #0d0d0d; --text-primary: #ffffff;
      --text-secondary: #c3c2b7; --muted: #898781; --grid: #2c2c2a;
      --baseline: #383835; --series-1: #3987e5; --series-2: #199e70;
      --border: rgba(255,255,255,0.10);
      --seq-100: #10305a; --seq-250: #184f95; --seq-450: #3987e5; --seq-650: #9ec5f4;
    }
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--page); color: var(--text-primary);
    font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
    padding: 24px 32px 64px;
  }
  h1 { font-size: 20px; margin: 0 0 4px; }
  .subtitle { color: var(--text-secondary); font-size: 13px; margin-bottom: 28px; }
  .card {
    background: var(--surface-1); border: 1px solid var(--border);
    border-radius: 12px; padding: 20px 24px; margin-bottom: 28px;
  }
  .card h2 { font-size: 15px; margin: 0 0 2px; }
  .card .hint { color: var(--muted); font-size: 12px; margin-bottom: 16px; }
  .controls { display: flex; gap: 8px; margin-bottom: 14px; flex-wrap: wrap; }
  button.tab {
    border: 1px solid var(--border); background: transparent; color: var(--text-secondary);
    padding: 5px 12px; border-radius: 999px; font-size: 12px; cursor: pointer;
  }
  button.tab.active { background: var(--series-1); color: white; border-color: transparent; }
  .legend { display: flex; gap: 16px; font-size: 12px; color: var(--text-secondary); margin-bottom: 8px; }
  .legend-item { display: flex; align-items: center; gap: 6px; }
  .legend-swatch { width: 14px; height: 3px; border-radius: 2px; }
  svg text { fill: var(--text-secondary); font-size: 11px; }
  .axis-line { stroke: var(--baseline); stroke-width: 1; }
  .grid-line { stroke: var(--grid); stroke-width: 1; }
  #tooltip {
    position: fixed; pointer-events: none; background: var(--text-primary); color: var(--surface-1);
    padding: 6px 10px; border-radius: 6px; font-size: 12px; display: none; z-index: 10;
    max-width: 280px;
  }
  #tooltip .val { font-weight: 700; }
  .heat-cell { stroke: var(--surface-1); stroke-width: 1; }
  .heat-cell:hover { stroke: var(--text-primary); stroke-width: 1.5; }
  .scatter-pt { fill: var(--series-1); opacity: 0.75; }
  .scatter-pt:hover { opacity: 1; stroke: var(--text-primary); stroke-width: 1; }
  .empty-note { color: var(--muted); font-size: 13px; font-style: italic; }
</style>
</head>
<body>
<h1>Loom</h1>
<div class="subtitle">a tiny LLM built from scratch - live introspection of a trained checkpoint</div>

<div class="card">
  <h2>Training loss / validation perplexity</h2>
  <div class="hint">real loss recorded during training, not synthetic</div>
  <div id="lossLegend" class="legend"></div>
  <svg id="lossChart" width="100%" height="280" viewBox="0 0 900 280" preserveAspectRatio="xMidYMid meet"></svg>
</div>

<div class="card">
  <h2>Causal self-attention</h2>
  <div class="hint">prompt: <code id="promptLabel"></code> - pick a layer and head; darker = more attention weight</div>
  <div class="controls" id="layerTabs"></div>
  <div class="controls" id="headTabs"></div>
  <svg id="attnHeatmap" width="100%" height="480" viewBox="0 0 560 560" preserveAspectRatio="xMidYMid meet"></svg>
</div>

<div class="card">
  <h2>Token embedding space (PCA, top 2 components)</h2>
  <div class="hint">from-scratch power-iteration PCA over the learned embedding table (`vocabSize` tokens)</div>
  <svg id="embedScatter" width="100%" height="480" viewBox="0 0 560 560" preserveAspectRatio="xMidYMid meet"></svg>
</div>

<div id="tooltip"></div>

<script>
const DATA = __LOOM_DATA__;
const tooltip = document.getElementById('tooltip');

function showTooltip(evt, html) {
  tooltip.innerHTML = html;
  tooltip.style.display = 'block';
  tooltip.style.left = (evt.clientX + 14) + 'px';
  tooltip.style.top = (evt.clientY + 14) + 'px';
}
function hideTooltip() { tooltip.style.display = 'none'; }

const SVG_NS = 'http://www.w3.org/2000/svg';
function el(tag, attrs) {
  const e = document.createElementNS(SVG_NS, tag);
  for (const k in attrs) e.setAttribute(k, attrs[k]);
  return e;
}
// Token labels are untrusted data (arbitrary decoded corpus text), so they
// are always escaped through textContent before landing in tooltip HTML.
function escapeLabel(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

// ---------- loss chart ----------
(function renderLoss() {
  const svg = document.getElementById('lossChart');
  const legend = document.getElementById('lossLegend');
  const { step, train_loss, val_loss } = DATA.history;
  if (!step || step.length === 0) {
    svg.appendChild(el('text', { x: 20, y: 30, fill: 'var(--muted)' })).textContent =
      'no training history recorded yet';
    return;
  }

  const W = 900, H = 280, padL = 46, padR = 20, padT = 16, padB = 30;
  const plotW = W - padL - padR, plotH = H - padT - padB;
  const allY = train_loss.concat(val_loss);
  const yMin = Math.min(...allY), yMax = Math.max(...allY);
  const yPad = (yMax - yMin) * 0.08 || 0.1;
  const y0 = yMin - yPad, y1 = yMax + yPad;
  const xMin = step[0], xMax = step[step.length - 1] || 1;

  const sx = s => padL + (xMax === xMin ? 0 : (s - xMin) / (xMax - xMin)) * plotW;
  const sy = v => padT + (1 - (v - y0) / (y1 - y0)) * plotH;

  // gridlines + y ticks
  const nTicks = 5;
  for (let i = 0; i <= nTicks; i++) {
    const v = y0 + (y1 - y0) * i / nTicks;
    const yy = sy(v);
    svg.appendChild(el('line', { x1: padL, x2: W - padR, y1: yy, y2: yy, class: 'grid-line' }));
    const t = el('text', { x: padL - 8, y: yy + 4, 'text-anchor': 'end' });
    t.textContent = v.toFixed(2);
    svg.appendChild(t);
  }
  svg.appendChild(el('line', { x1: padL, x2: padL, y1: padT, y2: H - padB, class: 'axis-line' }));
  svg.appendChild(el('line', { x1: padL, x2: W - padR, y1: H - padB, y2: H - padB, class: 'axis-line' }));

  function path(series) {
    return series.map((v, i) => (i === 0 ? 'M' : 'L') + sx(step[i]) + ' ' + sy(v)).join(' ');
  }
  const seriesDefs = [
    { key: 'train_loss', data: train_loss, color: 'var(--series-1)', label: 'train loss' },
    { key: 'val_loss', data: val_loss, color: 'var(--series-2)', label: 'val loss' },
  ];
  for (const s of seriesDefs) {
    svg.appendChild(el('path', { d: path(s.data), fill: 'none', stroke: s.color, 'stroke-width': 2 }));
    const item = document.createElement('div');
    item.className = 'legend-item';
    const sw = document.createElement('span');
    sw.className = 'legend-swatch';
    sw.style.background = s.color;
    const label = document.createElement('span');
    label.textContent = s.label;
    item.appendChild(sw);
    item.appendChild(label);
    legend.appendChild(item);
  }

  // crosshair + tooltip hit layer
  const hit = el('rect', { x: padL, y: padT, width: plotW, height: plotH, fill: 'transparent' });
  const crosshair = el('line', {
    x1: 0, x2: 0, y1: padT, y2: H - padB, stroke: 'var(--muted)', 'stroke-width': 1,
    'stroke-dasharray': '3,3', visibility: 'hidden',
  });
  svg.appendChild(crosshair);
  svg.appendChild(hit);
  hit.addEventListener('pointermove', (evt) => {
    const rect = svg.getBoundingClientRect();
    const px = (evt.clientX - rect.left) * (W / rect.width);
    const frac = Math.min(1, Math.max(0, (px - padL) / plotW));
    const idx = Math.round(frac * (step.length - 1));
    crosshair.setAttribute('x1', sx(step[idx]));
    crosshair.setAttribute('x2', sx(step[idx]));
    crosshair.setAttribute('visibility', 'visible');
    const ppl = Math.exp(val_loss[idx]);
    showTooltip(evt,
      `step <span class="val">${step[idx]}</span><br>` +
      `train loss <span class="val">${train_loss[idx].toFixed(4)}</span><br>` +
      `val loss <span class="val">${val_loss[idx].toFixed(4)}</span><br>` +
      `val perplexity <span class="val">${ppl.toFixed(2)}</span>`);
  });
  hit.addEventListener('pointerleave', () => { hideTooltip(); crosshair.setAttribute('visibility', 'hidden'); });
})();

// ---------- attention heatmap ----------
(function renderAttention() {
  document.getElementById('promptLabel').textContent = DATA.prompt;
  const layerTabs = document.getElementById('layerTabs');
  const headTabs = document.getElementById('headTabs');
  const svg = document.getElementById('attnHeatmap');
  let curLayer = 0, curHead = 0;

  function makeTab(container, label, isActive, onClick) {
    const b = document.createElement('button');
    b.className = 'tab' + (isActive ? ' active' : '');
    b.textContent = label;
    b.addEventListener('click', onClick);
    container.appendChild(b);
    return b;
  }

  function draw() {
    svg.innerHTML = '';
    if (DATA.nLayer === 0) {
      svg.appendChild(el('text', { x: 20, y: 30, fill: 'var(--muted)', 'font-style': 'italic' }))
        .textContent = 'this model has 0 transformer blocks - no attention to show';
      return;
    }
    const T = DATA.tokenLabels.length;
    const grid = DATA.attnLayers[curLayer][curHead]; // T x T
    const W = 560, pad = 90, size = W - pad;
    const cell = size / T;

    for (let i = 0; i < T; i++) {
      for (let j = 0; j < T; j++) {
        const w = grid[i][j];
        const c = svg.appendChild(el('rect', {
          x: pad + j * cell, y: pad + i * cell, width: cell, height: cell,
          class: 'heat-cell', fill: heatColor(w),
        }));
        c.addEventListener('pointermove', (evt) => showTooltip(evt,
          `query <span class="val">${escapeLabel(DATA.tokenLabels[i])}</span> &rarr; ` +
          `key <span class="val">${escapeLabel(DATA.tokenLabels[j])}</span><br>` +
          `weight <span class="val">${w.toFixed(4)}</span>`));
        c.addEventListener('pointerleave', hideTooltip);
      }
    }
    for (let i = 0; i < T; i++) {
      const t1 = el('text', { x: pad - 6, y: pad + i * cell + cell * 0.7, 'text-anchor': 'end' });
      t1.textContent = DATA.tokenLabels[i];
      svg.appendChild(t1);
      const t2 = el('text', {
        x: pad + i * cell + cell * 0.5, y: pad - 8, 'text-anchor': 'middle',
        transform: `rotate(-60 ${pad + i * cell + cell * 0.5} ${pad - 8})`,
      });
      t2.textContent = DATA.tokenLabels[i];
      svg.appendChild(t2);
    }
  }

  function heatColor(w) {
    // sequential single-hue ramp (blue), light -> dark by magnitude
    const stops = ['var(--seq-100)', 'var(--seq-250)', 'var(--seq-450)', 'var(--seq-650)'];
    const t = Math.max(0, Math.min(1, w));
    const idx = Math.min(stops.length - 2, Math.floor(t * (stops.length - 1)));
    return stops[idx + (t > 0.5 ? 1 : 0)];
  }

  for (let l = 0; l < DATA.nLayer; l++) {
    makeTab(layerTabs, 'layer ' + l, l === curLayer, () => {
      curLayer = l;
      [...layerTabs.children].forEach((c, i) => c.classList.toggle('active', i === l));
      draw();
    });
  }
  for (let h = 0; h < DATA.nHead; h++) {
    makeTab(headTabs, 'head ' + h, h === curHead, () => {
      curHead = h;
      [...headTabs.children].forEach((c, i) => c.classList.toggle('active', i === h));
      draw();
    });
  }
  draw();
})();

// ---------- embedding PCA scatter ----------
(function renderEmbeddings() {
  const svg = document.getElementById('embedScatter');
  const pts = DATA.embeddingPoints;
  const W = 560, H = 560, pad = 30;
  const xs = pts.map(p => p.x), ys = pts.map(p => p.y);
  const xMin = Math.min(...xs), xMax = Math.max(...xs);
  const yMin = Math.min(...ys), yMax = Math.max(...ys);
  const sx = v => pad + (xMax === xMin ? 0.5 : (v - xMin) / (xMax - xMin)) * (W - 2 * pad);
  const sy = v => H - pad - (yMax === yMin ? 0.5 : (v - yMin) / (yMax - yMin)) * (H - 2 * pad);

  svg.appendChild(el('line', { x1: pad, x2: W - pad, y1: H / 2, y2: H / 2, class: 'grid-line' }));
  svg.appendChild(el('line', { x1: W / 2, x2: W / 2, y1: pad, y2: H - pad, class: 'grid-line' }));

  for (const p of pts) {
    const c = svg.appendChild(el('circle', {
      cx: sx(p.x), cy: sy(p.y), r: 4, class: 'scatter-pt',
    }));
    const hit = svg.appendChild(el('circle', {
      cx: sx(p.x), cy: sy(p.y), r: 12, fill: 'transparent',
    }));
    const show = (evt) => showTooltip(evt, `token <span class="val">"${escapeLabel(p.label)}"</span>`);
    hit.addEventListener('pointermove', show);
    hit.addEventListener('pointerleave', hideTooltip);
  }
})();
</script>
</body>
</html>
"""
