"""Self-contained HTML visualizer: per-layer/per-head attention heatmaps for
a prompt, plus a loss-curve chart from a training log. No server, no external
JS/CSS libraries — everything (data + renderer) is embedded in one file.
"""
import json
import os

import numpy as np

_TEMPLATE = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Loom — attention &amp; training viz</title>
<style>
  .viz-root {
    color-scheme: light;
    --surface-1:      #fcfcfb;
    --page:           #f9f9f7;
    --text-primary:   #0b0b0b;
    --text-secondary: #52514e;
    --text-muted:     #898781;
    --gridline:       #e1e0d9;
    --baseline:       #c3c2b7;
    --border:         rgba(11,11,11,0.10);
    --series-1:       #256abf;
  }
  @media (prefers-color-scheme: dark) {
    :root:where(:not([data-theme="light"])) .viz-root {
      color-scheme: dark;
      --surface-1:      #1a1a19;
      --page:           #0d0d0d;
      --text-primary:   #ffffff;
      --text-secondary: #c3c2b7;
      --text-muted:     #898781;
      --gridline:       #2c2c2a;
      --baseline:       #383835;
      --border:         rgba(255,255,255,0.10);
      --series-1:       #3987e5;
    }
  }
  :root[data-theme="dark"] .viz-root {
    color-scheme: dark;
    --surface-1:      #1a1a19;
    --page:           #0d0d0d;
    --text-primary:   #ffffff;
    --text-secondary: #c3c2b7;
    --text-muted:     #898781;
    --gridline:       #2c2c2a;
    --baseline:       #383835;
    --border:         rgba(255,255,255,0.10);
    --series-1:       #3987e5;
  }
  * { box-sizing: border-box; }
  body { margin: 0; }
  .viz-root {
    font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
    color: var(--text-primary);
    background: var(--page);
    min-height: 100vh;
    padding: 28px 24px 48px;
  }
  h1 { font-size: 19px; font-weight: 600; margin: 0 0 4px; }
  .sub { color: var(--text-secondary); font-size: 13px; margin-bottom: 22px; }
  .panel {
    background: var(--surface-1); border: 1px solid var(--border);
    border-radius: 10px; padding: 18px; margin-bottom: 20px;
    max-width: 940px;
  }
  .panel h2 { font-size: 14px; font-weight: 600; margin: 0 0 12px; }
  .controls { display: flex; gap: 14px; align-items: center; margin-bottom: 14px;
              flex-wrap: wrap; font-size: 13px; color: var(--text-secondary); }
  select {
    background: var(--page); color: var(--text-primary); border: 1px solid var(--border);
    border-radius: 6px; padding: 4px 8px; font-size: 13px;
  }
  #tokrow { font-size: 12px; color: var(--text-muted); white-space: pre-wrap; word-break: break-all;
            margin: 0 0 10px; line-height: 1.6; }
  .heatwrap { display: flex; gap: 18px; align-items: flex-start; flex-wrap: wrap; }
  #heat { display: block; border-radius: 4px; }
  .legend-scale { display: flex; flex-direction: column; gap: 6px; font-size: 11px;
                  color: var(--text-muted); align-items: center; }
  .legend-scale canvas { border-radius: 3px; border: 1px solid var(--border); }
  .tooltip {
    position: fixed; pointer-events: none; background: var(--surface-1);
    border: 1px solid var(--border); border-radius: 6px; padding: 6px 10px;
    font-size: 12px; color: var(--text-primary); box-shadow: 0 2px 10px rgba(0,0,0,0.25);
    display: none; z-index: 10; line-height: 1.5;
  }
  .tooltip b { color: var(--series-1); }
  canvas#loss { display: block; }
  .loss-caption { font-size: 12px; color: var(--text-muted); margin-top: 8px; }
  .footnote { font-size: 12px; color: var(--text-muted); margin-top: 6px; }
</style>
</head>
<body>
<div class="viz-root">
<h1>Loom</h1>
<div class="sub">from-scratch transformer LM &mdash; attention heatmaps and training loss, generated statically, no server</div>

<div class="panel">
  <h2>Attention</h2>
  <div class="controls">
    <label>Layer <select id="layerSel"></select></label>
    <label>Head <select id="headSel"></select></label>
  </div>
  <div id="tokrow"></div>
  <div class="heatwrap">
    <canvas id="heat"></canvas>
    <div class="legend-scale">
      <span>high</span>
      <canvas id="legend" width="14" height="160"></canvas>
      <span>low</span>
    </div>
  </div>
  <div class="footnote">rows = query position (the token attending) &middot; columns = key position (the token attended to) &middot; hover a cell for its exact weight &middot; blank lower-right triangle is the causal mask</div>
</div>

<div class="panel">
  <h2>Training loss</h2>
  <canvas id="loss" width="880" height="240"></canvas>
  <div class="loss-caption" id="lossCaption"></div>
</div>

<div class="tooltip" id="tooltip"></div>
</div>

<script>
const DATA = __DATA_JSON__;

const root = document.querySelector('.viz-root');
const cssVar = (name) => getComputedStyle(root).getPropertyValue(name).trim();
const tooltip = document.getElementById('tooltip');

function showTooltip(x, y, html) {
  tooltip.innerHTML = html;
  tooltip.style.left = (x + 14) + 'px';
  tooltip.style.top = (y + 14) + 'px';
  tooltip.style.display = 'block';
}
function hideTooltip() { tooltip.style.display = 'none'; }

// Sequential blue ramp (light->dark), per the reference palette.
const RAMP_STOPS = ['#cde2fb', '#9ec5f4', '#6da7ec', '#3987e5', '#256abf', '#184f95', '#0d366b'];
function hexToRgb(hex) {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}
const RAMP_RGB = RAMP_STOPS.map(hexToRgb);
function rampColor(t) {
  t = Math.max(0, Math.min(1, t));
  const scaled = t * (RAMP_RGB.length - 1);
  const i = Math.min(RAMP_RGB.length - 2, Math.floor(scaled));
  const frac = scaled - i;
  const a = RAMP_RGB[i], b = RAMP_RGB[i + 1];
  const c = [0, 1, 2].map(k => Math.round(a[k] + (b[k] - a[k]) * frac));
  return `rgb(${c[0]}, ${c[1]}, ${c[2]})`;
}

function renderLegend() {
  const canvas = document.getElementById('legend');
  const ctx = canvas.getContext('2d');
  for (let y = 0; y < canvas.height; y++) {
    const t = 1 - y / (canvas.height - 1); // high at top
    ctx.fillStyle = rampColor(t);
    ctx.fillRect(0, y, canvas.width, 1);
  }
}

function renderAttention() {
  const layerSel = document.getElementById('layerSel');
  const headSel = document.getElementById('headSel');
  layerSel.innerHTML = '';
  DATA.attn.forEach((_, i) => {
    const o = document.createElement('option'); o.value = i; o.textContent = 'Layer ' + i;
    layerSel.appendChild(o);
  });
  const nHeads = DATA.attn.length ? DATA.attn[0].length : 0;
  headSel.innerHTML = '';
  for (let h = 0; h < nHeads; h++) {
    const o = document.createElement('option'); o.value = h; o.textContent = 'Head ' + h;
    headSel.appendChild(o);
  }

  const tokrow = document.getElementById('tokrow');
  tokrow.textContent = DATA.tokens.map((t, i) => `${i}:${JSON.stringify(t)}`).join('  ');

  const canvas = document.getElementById('heat');
  const T = DATA.tokens.length;
  const cell = Math.max(4, Math.min(28, Math.floor(620 / Math.max(1, T))));
  canvas.width = cell * T;
  canvas.height = cell * T;
  const ctx = canvas.getContext('2d');
  const surface = cssVar('--surface-1');

  let currentMat = null, currentMax = 1e-9;

  function draw() {
    const L = parseInt(layerSel.value, 10) || 0;
    const H = parseInt(headSel.value, 10) || 0;
    const mat = DATA.attn[L][H]; // T x T, row-major, already causal-masked (0 above diagonal)
    let maxV = 1e-9;
    for (const row of mat) for (const v of row) if (v > maxV) maxV = v;
    currentMat = mat; currentMax = maxV;
    ctx.fillStyle = surface;
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    for (let i = 0; i < T; i++) {
      for (let j = 0; j <= i; j++) {
        const v = mat[i][j] / maxV;
        ctx.fillStyle = rampColor(v);
        ctx.fillRect(j * cell, i * cell, cell - 1, cell - 1);
      }
    }
  }
  layerSel.onchange = draw;
  headSel.onchange = draw;

  canvas.onmousemove = (ev) => {
    const rect = canvas.getBoundingClientRect();
    const i = Math.floor((ev.clientY - rect.top) / cell);
    const j = Math.floor((ev.clientX - rect.left) / cell);
    if (i < 0 || i >= T || j < 0 || j >= T || j > i || !currentMat) { hideTooltip(); return; }
    const w = currentMat[i][j];
    const qTok = JSON.stringify(DATA.tokens[i]);
    const kTok = JSON.stringify(DATA.tokens[j]);
    showTooltip(ev.clientX, ev.clientY,
      `query <b>${i}</b> ${qTok} &rarr; key <b>${j}</b> ${kTok}<br>weight <b>${w.toFixed(4)}</b>`);
  };
  canvas.onmouseleave = hideTooltip;

  draw();
}

function renderLoss() {
  const canvas = document.getElementById('loss');
  const ctx = canvas.getContext('2d');
  const pts = DATA.loss;
  const gridline = cssVar('--gridline');
  const baseline = cssVar('--baseline');
  const muted = cssVar('--text-muted');
  const seriesColor = cssVar('--series-1');
  const caption = document.getElementById('lossCaption');

  ctx.clearRect(0, 0, canvas.width, canvas.height);
  if (!pts.length) {
    ctx.fillStyle = muted;
    ctx.font = '13px sans-serif';
    ctx.fillText('no training log provided', 20, 24);
    caption.textContent = '';
    return;
  }
  const pad = { l: 52, r: 16, t: 16, b: 30 };
  const W = canvas.width - pad.l - pad.r, H = canvas.height - pad.t - pad.b;
  const xs = pts.map(p => p.step), ys = pts.map(p => p.loss);
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const minY = Math.min(...ys), maxY = Math.max(...ys);
  const sx = x => pad.l + (maxX > minX ? (x - minX) / (maxX - minX) : 0) * W;
  const sy = y => pad.t + H - (maxY > minY ? (y - minY) / (maxY - minY) : 0) * H;

  // gridlines (recessive, hairline)
  ctx.strokeStyle = gridline;
  ctx.lineWidth = 1;
  const nTicks = 4;
  ctx.font = '11px sans-serif';
  ctx.fillStyle = muted;
  ctx.textAlign = 'right';
  for (let k = 0; k <= nTicks; k++) {
    const yv = minY + (maxY - minY) * k / nTicks;
    const yy = sy(yv);
    ctx.beginPath(); ctx.moveTo(pad.l, yy); ctx.lineTo(pad.l + W, yy); ctx.stroke();
    ctx.fillText(yv.toFixed(2), pad.l - 8, yy + 3);
  }

  // baseline
  ctx.strokeStyle = baseline;
  ctx.beginPath(); ctx.moveTo(pad.l, pad.t + H); ctx.lineTo(pad.l + W, pad.t + H); ctx.stroke();

  // the line (2px, single series -> no legend box needed per style guide)
  ctx.strokeStyle = seriesColor;
  ctx.lineWidth = 2;
  ctx.lineJoin = 'round'; ctx.lineCap = 'round';
  ctx.beginPath();
  pts.forEach((p, i) => {
    const x = sx(p.step), y = sy(p.loss);
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  });
  ctx.stroke();

  // end marker + direct label at the last point
  const last = pts[pts.length - 1];
  const lx = sx(last.step), ly = sy(last.loss);
  ctx.fillStyle = surfaceOf(canvas);
  ctx.beginPath(); ctx.arc(lx, ly, 5, 0, 2 * Math.PI); ctx.fill();
  ctx.fillStyle = seriesColor;
  ctx.beginPath(); ctx.arc(lx, ly, 4, 0, 2 * Math.PI); ctx.fill();
  ctx.fillStyle = cssVar('--text-primary');
  ctx.textAlign = 'left';
  ctx.font = '12px sans-serif';
  ctx.fillText(last.loss.toFixed(3), Math.min(lx + 8, canvas.width - 40), ly - 8);

  ctx.textAlign = 'left';
  ctx.fillStyle = muted;
  ctx.fillText('step ' + minX, pad.l, canvas.height - 8);
  ctx.textAlign = 'right';
  ctx.fillText('step ' + maxX, pad.l + W, canvas.height - 8);

  caption.textContent = `${pts.length} logged points, loss ${pts[0].loss.toFixed(3)} → ${last.loss.toFixed(3)}`;

  // hover crosshair + tooltip
  canvas.onmousemove = (ev) => {
    const rect = canvas.getBoundingClientRect();
    const mx = ev.clientX - rect.left;
    if (mx < pad.l || mx > pad.l + W) { hideTooltip(); return; }
    const frac = (mx - pad.l) / W;
    const targetStep = minX + frac * (maxX - minX);
    let nearest = pts[0], bestDist = Infinity;
    for (const p of pts) {
      const d = Math.abs(p.step - targetStep);
      if (d < bestDist) { bestDist = d; nearest = p; }
    }
    showTooltip(ev.clientX, ev.clientY, `step <b>${nearest.step}</b><br>loss <b>${nearest.loss.toFixed(4)}</b>`);
  };
  canvas.onmouseleave = hideTooltip;

  function surfaceOf(c) { return cssVar('--surface-1'); }
}

renderLegend();
renderAttention();
renderLoss();
</script>
</body>
</html>
"""


def render(prompt, model, tokenizer, log_path=None, out_path="viz.html", max_context=48):
    max_context = min(max_context, model.max_seq_len)
    ids = tokenizer.encode(prompt)[:max_context] or [0]
    tokens = [tokenizer.decode([i]) for i in ids]

    arr = np.array([ids], dtype=np.int64)
    _, probs_all = model.forward(arr)
    # probs_all: list of (1, H, T, T) -> nested python lists for JSON
    attn = [layer_probs[0].tolist() for layer_probs in probs_all]

    loss_points = []
    if log_path and os.path.exists(log_path):
        with open(log_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                loss_points.append({"step": rec["step"], "loss": rec["loss"]})

    data = {"tokens": tokens, "attn": attn, "loss": loss_points}
    # Escape "</" so no embedded token/prompt content can prematurely close
    # the surrounding <script> block (defense in depth for arbitrary
    # --prompt / corpus content flowing into this generated HTML).
    data_json = json.dumps(data).replace("</", "<\\/")
    html = _TEMPLATE.replace("__DATA_JSON__", data_json)

    out_dir = os.path.dirname(os.path.abspath(out_path))
    os.makedirs(out_dir, exist_ok=True)
    with open(out_path, "w") as f:
        f.write(html)
    return out_path
