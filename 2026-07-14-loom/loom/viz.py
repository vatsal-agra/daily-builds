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
  :root { color-scheme: dark light; }
  body { font-family: -apple-system, Segoe UI, Helvetica, Arial, sans-serif;
         background: #0f1115; color: #e6e6e6; margin: 0; padding: 24px; }
  h1 { font-size: 20px; font-weight: 600; margin: 0 0 4px; }
  .sub { color: #9aa0a6; font-size: 13px; margin-bottom: 20px; }
  .panel { background: #171a21; border: 1px solid #2a2f3a; border-radius: 10px;
           padding: 16px; margin-bottom: 20px; }
  .controls { display: flex; gap: 12px; align-items: center; margin-bottom: 12px;
              flex-wrap: wrap; font-size: 13px; }
  select { background: #232733; color: #e6e6e6; border: 1px solid #353b48;
           border-radius: 6px; padding: 4px 8px; }
  #heat { display: block; margin: 0 auto; image-rendering: pixelated; }
  #tokrow { font-size: 12px; color: #9aa0a6; white-space: pre-wrap; word-break: break-all;
            max-width: 900px; margin: 0 auto 8px; text-align: center; }
  canvas#loss { background: #0f1115; }
  .legend { font-size: 12px; color: #9aa0a6; margin-top: 6px; }
</style>
</head>
<body>
<h1>Loom</h1>
<div class="sub">from-scratch transformer LM &mdash; attention heatmaps and training loss, generated statically, no server</div>

<div class="panel">
  <div class="controls">
    <label>Layer <select id="layerSel"></select></label>
    <label>Head <select id="headSel"></select></label>
  </div>
  <div id="tokrow"></div>
  <canvas id="heat"></canvas>
  <div class="legend">rows = query position (the token attending), columns = key position (the token attended to). Brighter = higher attention weight. Lower-right triangle only (causal mask).</div>
</div>

<div class="panel">
  <div class="controls"><b>Training loss</b></div>
  <canvas id="loss" width="900" height="260"></canvas>
</div>

<script>
const DATA = __DATA_JSON__;

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
  const cell = Math.max(4, Math.min(28, Math.floor(700 / Math.max(1, T))));
  canvas.width = cell * T;
  canvas.height = cell * T;
  const ctx = canvas.getContext('2d');

  function draw() {
    const L = parseInt(layerSel.value, 10) || 0;
    const H = parseInt(headSel.value, 10) || 0;
    const mat = DATA.attn[L][H]; // T x T, row-major, already causal-masked (0 above diagonal)
    let maxV = 1e-9;
    for (const row of mat) for (const v of row) if (v > maxV) maxV = v;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    for (let i = 0; i < T; i++) {
      for (let j = 0; j < T; j++) {
        const v = mat[i][j] / maxV;
        const c = Math.round(v * 255);
        ctx.fillStyle = `rgb(${c}, ${Math.round(c*0.6)}, ${Math.round(255-c*0.3)})`;
        ctx.fillRect(j * cell, i * cell, cell - 1, cell - 1);
      }
    }
  }
  layerSel.onchange = draw;
  headSel.onchange = draw;
  draw();
}

function renderLoss() {
  const canvas = document.getElementById('loss');
  const ctx = canvas.getContext('2d');
  const pts = DATA.loss;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  if (!pts.length) {
    ctx.fillStyle = '#9aa0a6';
    ctx.fillText('no training log provided', 20, 20);
    return;
  }
  const pad = 40;
  const W = canvas.width - 2 * pad, H = canvas.height - 2 * pad;
  const xs = pts.map(p => p.step), ys = pts.map(p => p.loss);
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const minY = Math.min(...ys), maxY = Math.max(...ys);
  const sx = x => pad + (maxX > minX ? (x - minX) / (maxX - minX) : 0) * W;
  const sy = y => pad + H - (maxY > minY ? (y - minY) / (maxY - minY) : 0) * H;

  ctx.strokeStyle = '#353b48';
  ctx.beginPath(); ctx.moveTo(pad, pad); ctx.lineTo(pad, pad + H); ctx.lineTo(pad + W, pad + H); ctx.stroke();

  ctx.strokeStyle = '#6ea8fe';
  ctx.lineWidth = 2;
  ctx.beginPath();
  pts.forEach((p, i) => {
    const x = sx(p.step), y = sy(p.loss);
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  });
  ctx.stroke();

  ctx.fillStyle = '#9aa0a6';
  ctx.font = '12px sans-serif';
  ctx.fillText(minY.toFixed(3), 4, sy(minY));
  ctx.fillText(maxY.toFixed(3), 4, sy(maxY));
  ctx.fillText('step ' + minX, pad, pad + H + 16);
  ctx.fillText('step ' + maxX, pad + W - 50, pad + H + 16);
}

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
