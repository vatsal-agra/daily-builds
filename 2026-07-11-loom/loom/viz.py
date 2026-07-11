"""Renders a self-contained interactive HTML page: a real loss curve, a
token-by-token generation replay, and per-layer/per-head attention heatmaps
-- all built from data captured off an actual forward pass (`sample.generate`
with `capture_attn=True`), not fabricated.

Colors follow the project's dataviz skill: a single-hue sequential blue ramp
for the attention-weight heatmap (a magnitude encoding), and the first two
fixed categorical slots (blue/aqua) for the two loss-curve series, both
modes selected (light and dark, not an automatic filter-flip).
"""
import json


def _safe_json(obj):
    """json.dumps, escaped so a `</script>` inside any string value (e.g. a
    prompt or generated token containing literal HTML) can't break out of
    the embedding <script> tag."""
    return json.dumps(obj).replace("</", "<\\/")


def _loss_curve_svg(history):
    if not history:
        return '<p class="muted">No training history available.</p>'
    W, H = 640, 220
    pad_l, pad_r, pad_t, pad_b = 44, 16, 16, 28
    steps = [h["step"] for h in history]
    trains = [h["train_loss"] for h in history]
    vals = [h["val_loss"] for h in history]
    all_y = trains + vals
    y_min, y_max = min(all_y), max(all_y)
    if y_max - y_min < 1e-6:
        y_max = y_min + 1.0
    x_min, x_max = min(steps), max(steps)
    if x_max - x_min < 1:
        x_max = x_min + 1

    def sx(s):
        return pad_l + (s - x_min) / (x_max - x_min) * (W - pad_l - pad_r)

    def sy(v):
        return H - pad_b - (v - y_min) / (y_max - y_min) * (H - pad_t - pad_b)

    def polyline(vals_):
        pts = " ".join(f"{sx(s):.1f},{sy(v):.1f}" for s, v in zip(steps, vals_))
        return pts

    # 4 horizontal gridlines
    grid = []
    for i in range(5):
        y = pad_t + i * (H - pad_t - pad_b) / 4
        val = y_max - i * (y_max - y_min) / 4
        grid.append(f'<line x1="{pad_l}" y1="{y:.1f}" x2="{W - pad_r}" y2="{y:.1f}" class="gridline"/>'
                     f'<text x="{pad_l - 6}" y="{y + 3:.1f}" class="axis-label" text-anchor="end">{val:.2f}</text>')
    x_ticks = []
    n_ticks = min(6, len(steps))
    for i in range(n_ticks):
        idx = int(i * (len(steps) - 1) / max(1, n_ticks - 1))
        s = steps[idx]
        x_ticks.append(f'<text x="{sx(s):.1f}" y="{H - pad_b + 16}" class="axis-label" text-anchor="middle">{s}</text>')

    dots_train = "".join(f'<circle cx="{sx(s):.1f}" cy="{sy(v):.1f}" r="2.5" class="dot-train" data-step="{s}" data-val="{v:.4f}"/>'
                          for s, v in zip(steps, trains))
    dots_val = "".join(f'<circle cx="{sx(s):.1f}" cy="{sy(v):.1f}" r="2.5" class="dot-val" data-step="{s}" data-val="{v:.4f}"/>'
                        for s, v in zip(steps, vals))

    return f'''
<svg viewBox="0 0 {W} {H}" class="loss-chart" role="img" aria-label="Training and validation loss over steps">
  {''.join(grid)}
  <polyline points="{polyline(trains)}" class="line-train" fill="none"/>
  <polyline points="{polyline(vals)}" class="line-val" fill="none"/>
  {dots_train}
  {dots_val}
  {''.join(x_ticks)}
  <text x="{(W) / 2}" y="{H - 2}" class="axis-label" text-anchor="middle">step</text>
</svg>
<div class="legend">
  <span class="legend-item"><span class="swatch swatch-train"></span>train loss</span>
  <span class="legend-item"><span class="swatch swatch-val"></span>val loss</span>
</div>
'''


def render_html(model, tokenizer, meta, trace, prompt):
    history = meta.get("history", [])
    steps_payload = []
    for step in trace:
        ctx_tokens = [tokenizer.decode([i]) for i in step.get("context_ids", [])]
        steps_payload.append({
            "token_id": step["token_id"],
            "token_str": step["token_str"],
            "prob": step["prob"],
            "context_tokens": ctx_tokens,
            "attn": step.get("attn", []),
        })

    payload = {
        "prompt": prompt,
        "config": {
            "vocab_size": model.vocab_size,
            "block_size": model.block_size,
            "n_embd": model.n_embd,
            "n_head": model.n_head,
            "n_layer": model.n_layer,
        },
        "steps": steps_payload,
    }
    data_json = _safe_json(payload)
    loss_svg = _loss_curve_svg(history)
    generated_text = "".join(s["token_str"] for s in trace)

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Loom — attention &amp; generation visualizer</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root {{
    --surface-1: #fcfcfb; --page: #f9f9f7; --text-primary: #0b0b0b;
    --text-secondary: #52514e; --muted: #898781; --gridline: #e1e0d9;
    --baseline: #c3c2b7; --border: rgba(11,11,11,0.10);
    --series-1: #2a78d6; --series-2: #1baf7a;
    --seq-100: #cde2fb; --seq-250: #86b6ef; --seq-400: #3987e5;
    --seq-550: #1c5cab; --seq-700: #0d366b;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --surface-1: #1a1a19; --page: #0d0d0d; --text-primary: #ffffff;
      --text-secondary: #c3c2b7; --muted: #898781; --gridline: #2c2c2a;
      --baseline: #383835; --border: rgba(255,255,255,0.10);
      --series-1: #3987e5; --series-2: #199e70;
      --seq-100: #14314f; --seq-250: #184f95; --seq-400: #2a78d6;
      --seq-550: #5598e7; --seq-700: #9ec5f4;
    }}
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; background: var(--page); color: var(--text-primary);
    font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
    padding: 32px 20px 64px;
  }}
  .wrap {{ max-width: 980px; margin: 0 auto; }}
  h1 {{ font-size: 1.4rem; margin: 0 0 4px; }}
  .subtitle {{ color: var(--text-secondary); margin: 0 0 24px; font-size: 0.9rem; }}
  .card {{
    background: var(--surface-1); border: 1px solid var(--border);
    border-radius: 12px; padding: 20px 24px; margin-bottom: 20px;
  }}
  .card h2 {{ font-size: 1rem; margin: 0 0 12px; color: var(--text-primary); }}
  .muted {{ color: var(--muted); font-size: 0.85rem; }}
  .config-row {{ display: flex; flex-wrap: wrap; gap: 8px 20px; font-size: 0.82rem; color: var(--text-secondary); margin-bottom: 4px; }}
  .config-row b {{ color: var(--text-primary); font-weight: 600; }}

  .loss-chart {{ width: 100%; height: auto; }}
  .gridline {{ stroke: var(--gridline); stroke-width: 1; }}
  .axis-label {{ fill: var(--muted); font-size: 9px; }}
  .line-train {{ stroke: var(--series-1); stroke-width: 2; }}
  .line-val {{ stroke: var(--series-2); stroke-width: 2; }}
  .dot-train {{ fill: var(--series-1); }}
  .dot-val {{ fill: var(--series-2); }}
  .legend {{ display: flex; gap: 18px; margin-top: 6px; font-size: 0.8rem; color: var(--text-secondary); }}
  .legend-item {{ display: flex; align-items: center; gap: 6px; }}
  .swatch {{ width: 10px; height: 10px; border-radius: 2px; display: inline-block; }}
  .swatch-train {{ background: var(--series-1); }}
  .swatch-val {{ background: var(--series-2); }}

  .replay-text {{
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 0.95rem; line-height: 1.7; padding: 14px; border-radius: 8px;
    background: var(--page); border: 1px solid var(--border); white-space: pre-wrap;
    word-break: break-word; margin-bottom: 14px; max-height: 220px; overflow-y: auto;
  }}
  .tok {{ padding: 1px 0; }}
  .tok.current {{ background: var(--seq-250); border-radius: 3px; box-shadow: 0 0 0 1px var(--seq-400); }}
  .tok.future {{ opacity: 0.35; }}

  .controls {{ display: flex; align-items: center; gap: 12px; margin-bottom: 6px; }}
  .controls input[type=range] {{ flex: 1; }}
  .controls button {{
    background: var(--surface-1); border: 1px solid var(--border); color: var(--text-primary);
    border-radius: 6px; padding: 6px 12px; cursor: pointer; font-size: 0.85rem;
  }}
  .controls button:hover {{ background: var(--seq-100); }}
  .step-info {{ font-size: 0.85rem; color: var(--text-secondary); margin-top: 4px; }}
  .step-info b {{ color: var(--text-primary); }}

  .tabs {{ display: flex; gap: 6px; margin-bottom: 12px; flex-wrap: wrap; }}
  .tab {{
    border: 1px solid var(--border); background: var(--page); color: var(--text-secondary);
    border-radius: 6px; padding: 4px 10px; font-size: 0.8rem; cursor: pointer;
  }}
  .tab.active {{ background: var(--series-1); color: white; border-color: var(--series-1); }}

  .heatmap {{ display: grid; gap: 8px; }}
  .heat-row {{ display: grid; grid-auto-flow: column; gap: 3px; align-items: center; }}
  .heat-row-label {{ font-size: 0.7rem; color: var(--muted); width: 44px; text-align: right; padding-right: 4px; }}
  .heat-cell {{
    width: 20px; height: 20px; border-radius: 3px; position: relative; cursor: default;
  }}
  .heat-col-labels {{ display: grid; grid-auto-flow: column; gap: 3px; margin-left: 48px; margin-top: 4px; }}
  .heat-col-label {{
    width: 20px; font-size: 0.62rem; color: var(--muted); writing-mode: vertical-rl;
    text-orientation: mixed; max-height: 60px; overflow: hidden;
  }}
  .heat-scale {{ display: flex; align-items: center; gap: 8px; margin-top: 14px; font-size: 0.75rem; color: var(--muted); }}
  .heat-scale .ramp {{ width: 160px; height: 10px; border-radius: 5px;
    background: linear-gradient(to right, var(--seq-100), var(--seq-250), var(--seq-400), var(--seq-550), var(--seq-700)); }}
  #tooltip {{
    position: fixed; pointer-events: none; background: var(--text-primary); color: var(--surface-1);
    font-size: 0.75rem; padding: 4px 8px; border-radius: 4px; display: none; z-index: 10;
    max-width: 220px;
  }}
  footer {{ margin-top: 28px; color: var(--muted); font-size: 0.78rem; text-align: center; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>Loom — attention &amp; generation visualizer</h1>
  <p class="subtitle">Every number on this page comes from a real forward pass through a
    trained checkpoint — nothing here is mocked or hand-authored.</p>

  <div class="card">
    <h2>Model &amp; run configuration</h2>
    <div class="config-row" id="config-row"></div>
  </div>

  <div class="card">
    <h2>Training loss</h2>
    {loss_svg}
  </div>

  <div class="card">
    <h2>Generation replay</h2>
    <p class="muted">Prompt: <b id="prompt-label"></b></p>
    <div class="replay-text" id="replay-text"></div>
    <div class="controls">
      <button id="btn-prev">◀ prev</button>
      <button id="btn-play">▶ play</button>
      <button id="btn-next">next ▶</button>
      <input type="range" id="scrub" min="0" value="0" step="1">
    </div>
    <div class="step-info" id="step-info"></div>
  </div>

  <div class="card">
    <h2>Attention at the current step</h2>
    <p class="muted">The distribution the just-generated token used to attend back over its
      context, one row per head, for the selected layer. Darker = higher attention weight.</p>
    <div class="tabs" id="layer-tabs"></div>
    <div id="heatmap-container"></div>
    <div class="heat-scale">
      <span>0</span><div class="ramp"></div><span>max weight (this step/layer)</span>
    </div>
  </div>

  <footer>Loom · a Transformer trained on a from-scratch tensor autodiff engine · no PyTorch, no JAX</footer>
</div>
<div id="tooltip"></div>
<script>
const DATA = {data_json};

const cfg = DATA.config;
document.getElementById('config-row').innerHTML = `
  <span><b>vocab_size</b> ${{cfg.vocab_size}}</span>
  <span><b>block_size</b> ${{cfg.block_size}}</span>
  <span><b>n_embd</b> ${{cfg.n_embd}}</span>
  <span><b>n_head</b> ${{cfg.n_head}}</span>
  <span><b>n_layer</b> ${{cfg.n_layer}}</span>
`;
document.getElementById('prompt-label').textContent = DATA.prompt ? JSON.stringify(DATA.prompt) : '(empty — started from a random seed token)';

const steps = DATA.steps;
let currentStep = steps.length ? 0 : -1;
let currentLayer = 0;
let playing = false;
let playTimer = null;

const scrub = document.getElementById('scrub');
scrub.max = Math.max(0, steps.length - 1);

function renderLayerTabs() {{
  const tabs = document.getElementById('layer-tabs');
  tabs.innerHTML = '';
  for (let l = 0; l < cfg.n_layer; l++) {{
    const b = document.createElement('button');
    b.className = 'tab' + (l === currentLayer ? ' active' : '');
    b.textContent = 'layer ' + l;
    b.onclick = () => {{ currentLayer = l; render(); }};
    tabs.appendChild(b);
  }}
}}

function seqColor(t) {{
  // t in [0,1] -> interpolate across the 5-step sequential ramp
  const stops = [
    getComputedStyle(document.documentElement).getPropertyValue('--seq-100').trim(),
    getComputedStyle(document.documentElement).getPropertyValue('--seq-250').trim(),
    getComputedStyle(document.documentElement).getPropertyValue('--seq-400').trim(),
    getComputedStyle(document.documentElement).getPropertyValue('--seq-550').trim(),
    getComputedStyle(document.documentElement).getPropertyValue('--seq-700').trim(),
  ];
  const idx = Math.min(stops.length - 2, Math.floor(t * (stops.length - 1)));
  return stops[idx + 1];
}}

function renderReplayText() {{
  const el = document.getElementById('replay-text');
  el.innerHTML = '';
  const promptSpan = document.createElement('span');
  promptSpan.textContent = DATA.prompt;
  promptSpan.className = 'tok';
  el.appendChild(promptSpan);
  steps.forEach((s, i) => {{
    const span = document.createElement('span');
    span.textContent = s.token_str;
    span.className = 'tok' + (i === currentStep ? ' current' : (i > currentStep ? ' future' : ''));
    el.appendChild(span);
  }});
}}

function renderHeatmap() {{
  const container = document.getElementById('heatmap-container');
  container.innerHTML = '';
  if (currentStep < 0) {{ container.innerHTML = '<p class="muted">No generation trace.</p>'; return; }}
  const step = steps[currentStep];
  const attn = step.attn[currentLayer]; // (n_head, T)
  const tokens = step.context_tokens;
  let maxW = 1e-9;
  attn.forEach(row => row.forEach(v => {{ if (v > maxW) maxW = v; }}));

  const map = document.createElement('div');
  map.className = 'heatmap';
  attn.forEach((row, h) => {{
    const rowEl = document.createElement('div');
    rowEl.className = 'heat-row';
    const label = document.createElement('div');
    label.className = 'heat-row-label';
    label.textContent = 'head ' + h;
    rowEl.appendChild(label);
    row.forEach((v, j) => {{
      const cell = document.createElement('div');
      cell.className = 'heat-cell';
      cell.style.background = seqColor(v / maxW);
      cell.addEventListener('mousemove', (e) => showTooltip(e, `token ${{JSON.stringify(tokens[j])}} — weight ${{v.toFixed(4)}}`));
      cell.addEventListener('mouseleave', hideTooltip);
      rowEl.appendChild(cell);
    }});
    map.appendChild(rowEl);
  }});
  container.appendChild(map);

  const colLabels = document.createElement('div');
  colLabels.className = 'heat-col-labels';
  tokens.forEach(t => {{
    const el = document.createElement('div');
    el.className = 'heat-col-label';
    el.textContent = t.length > 8 ? t.slice(0, 8) + '…' : t;
    colLabels.appendChild(el);
  }});
  container.appendChild(colLabels);
}}

function showTooltip(e, text) {{
  const tip = document.getElementById('tooltip');
  tip.textContent = text;
  tip.style.left = (e.clientX + 12) + 'px';
  tip.style.top = (e.clientY + 12) + 'px';
  tip.style.display = 'block';
}}
function hideTooltip() {{ document.getElementById('tooltip').style.display = 'none'; }}

function renderStepInfo() {{
  const info = document.getElementById('step-info');
  if (currentStep < 0) {{ info.textContent = ''; return; }}
  const s = steps[currentStep];
  info.innerHTML = `step <b>${{currentStep + 1}}/${{steps.length}}</b> — sampled <b>${{JSON.stringify(s.token_str)}}</b> with probability <b>${{s.prob.toFixed(4)}}</b>`;
}}

function render() {{
  scrub.value = Math.max(0, currentStep);
  renderLayerTabs();
  renderReplayText();
  renderHeatmap();
  renderStepInfo();
}}

document.getElementById('btn-prev').onclick = () => {{ stopPlay(); currentStep = Math.max(0, currentStep - 1); render(); }};
document.getElementById('btn-next').onclick = () => {{ stopPlay(); currentStep = Math.min(steps.length - 1, currentStep + 1); render(); }};
scrub.oninput = () => {{ stopPlay(); currentStep = parseInt(scrub.value, 10); render(); }};

function stopPlay() {{
  playing = false;
  document.getElementById('btn-play').textContent = '▶ play';
  if (playTimer) {{ clearInterval(playTimer); playTimer = null; }}
}}

document.getElementById('btn-play').onclick = () => {{
  if (playing) {{ stopPlay(); return; }}
  playing = true;
  document.getElementById('btn-play').textContent = '⏸ pause';
  playTimer = setInterval(() => {{
    currentStep = currentStep + 1;
    if (currentStep >= steps.length) {{ stopPlay(); currentStep = steps.length - 1; }}
    render();
  }}, 350);
}};

render();
</script>
</body>
</html>
"""
