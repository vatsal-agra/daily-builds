"""Render a real per-layer, per-head attention-weight heatmap as a
self-contained interactive HTML page.

The attention values come from an actual forward pass of a trained model
on a user-supplied prompt (`GPT.__call__(..., capture_attn=True)`), not
fabricated or hand-authored data.
"""
from __future__ import annotations

import html
import json

import numpy as np

from loom.model import GPT
from loom.tokenizer import BPETokenizer

# Sequential single-hue (blue) ramp, light->dark, from the project's dataviz
# reference palette (references/palette.md), used for magnitude encoding.
_SEQUENTIAL_BLUE = [
    "#f4f9fe", "#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7",
    "#3987e5", "#2a78d6", "#256abf", "#1c5cab", "#184f95", "#104281", "#0d366b",
]


def _token_label(tok: BPETokenizer, token_id: int) -> str:
    raw = tok.id_bytes[token_id]
    try:
        s = raw.decode("utf-8")
    except UnicodeDecodeError:
        return "<0x" + raw.hex().upper() + ">"
    return s.replace("\n", "\\n").replace("\t", "\\t").replace(" ", "·")  # middle dot for space


def render_attention_html(model: GPT, tok: BPETokenizer, prompt: str) -> str:
    ids = tok.encode(prompt)
    if len(ids) == 0:
        raise ValueError("prompt encodes to zero tokens")
    context = ids[-model.block_size:]
    x = np.array([context])
    model(x, capture_attn=True)
    maps = model.attention_maps()  # list of (1, n_head, T, T), one per layer
    n_layer = len(maps)
    n_head = maps[0].shape[1]
    T = maps[0].shape[2]
    tokens = [_token_label(tok, t) for t in context]

    # data[layer][head] = T x T list of floats (0 for causally-masked cells)
    data = [[maps[layer][0, head].tolist() for head in range(n_head)] for layer in range(n_layer)]

    payload = {
        "tokens": tokens,
        "data": data,
        "n_layer": n_layer,
        "n_head": n_head,
        "T": T,
    }
    payload_json = json.dumps(payload)
    ramp_json = json.dumps(_SEQUENTIAL_BLUE)
    prompt_escaped = html.escape(prompt)
    config = model.config()
    config_str = (f"vocab_size={config['vocab_size']}  d_model={config['d_model']}  "
                  f"n_layer={config['n_layer']}  n_head={config['n_head']}  "
                  f"block_size={config['block_size']}")

    return _TEMPLATE.format(payload_json=payload_json, ramp_json=ramp_json,
                             prompt_escaped=prompt_escaped, config_str=html.escape(config_str))


_TEMPLATE = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Loom — attention weights</title>
<style>
  .viz-root {{
    color-scheme: light;
    --surface-1:      #fcfcfb;
    --page:           #f9f9f7;
    --text-primary:   #0b0b0b;
    --text-secondary: #52514e;
    --muted:          #898781;
    --gridline:       #e1e0d9;
    --border:         rgba(11,11,11,0.10);
    --mask-fill:      #eceae3;
  }}
  @media (prefers-color-scheme: dark) {{
    :root:where(:not([data-theme="light"])) .viz-root {{
      color-scheme: dark;
      --surface-1:      #1a1a19;
      --page:           #0d0d0d;
      --text-primary:   #ffffff;
      --text-secondary: #c3c2b7;
      --muted:          #898781;
      --gridline:       #2c2c2a;
      --border:         rgba(255,255,255,0.10);
      --mask-fill:      #242422;
    }}
  }}
  :root[data-theme="dark"] .viz-root {{
    color-scheme: dark;
    --surface-1:      #1a1a19;
    --page:           #0d0d0d;
    --text-primary:   #ffffff;
    --text-secondary: #c3c2b7;
    --muted:          #898781;
    --gridline:       #2c2c2a;
    --border:         rgba(255,255,255,0.10);
    --mask-fill:      #242422;
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; }}
  .viz-root {{
    background: var(--page);
    color: var(--text-primary);
    font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    padding: 24px;
    min-height: 100vh;
  }}
  h1 {{ font-size: 18px; margin: 0 0 4px; }}
  .subtitle {{ color: var(--text-secondary); font-size: 13px; margin-bottom: 4px; }}
  .config {{ color: var(--muted); font-size: 12px; margin-bottom: 20px; }}
  .prompt-box {{
    background: var(--surface-1); border: 1px solid var(--border); border-radius: 8px;
    padding: 10px 14px; margin-bottom: 20px; font-family: ui-monospace, monospace;
  }}
  .picker-row {{ display: flex; gap: 20px; align-items: center; flex-wrap: wrap; margin-bottom: 16px; }}
  .picker-group {{ display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }}
  .picker-label {{ color: var(--text-secondary); font-size: 12px; margin-right: 4px; }}
  button.pick {{
    border: 1px solid var(--border); background: var(--surface-1); color: var(--text-primary);
    border-radius: 6px; padding: 5px 11px; font-size: 13px; cursor: pointer;
  }}
  button.pick[aria-pressed="true"] {{
    background: {active_hue}; color: white; border-color: {active_hue};
  }}
  .chart-card {{
    background: var(--surface-1); border: 1px solid var(--border); border-radius: 10px;
    padding: 20px; overflow-x: auto;
  }}
  table.heat {{ border-collapse: collapse; }}
  table.heat th {{
    color: var(--text-secondary); font-weight: 400; font-size: 12px; font-family: ui-monospace, monospace;
    padding: 2px 4px; text-align: center; white-space: pre;
  }}
  table.heat th.rowhead {{ text-align: right; padding-right: 8px; }}
  td.cell {{
    width: 26px; height: 26px; border: 1px solid var(--gridline); text-align: center;
    cursor: default; position: relative;
  }}
  td.cell.masked {{ background: var(--mask-fill); }}
  td.cell:hover, td.cell:focus {{ outline: 2px solid var(--text-primary); outline-offset: -2px; }}
  .legend {{ display: flex; align-items: center; gap: 8px; margin-top: 16px; font-size: 12px; color: var(--text-secondary); }}
  .legend .ramp {{ width: 160px; height: 12px; border-radius: 3px; border: 1px solid var(--border); }}
  #tooltip {{
    position: fixed; pointer-events: none; background: var(--text-primary); color: var(--surface-1);
    padding: 6px 9px; border-radius: 6px; font-size: 12px; display: none; z-index: 10;
    font-family: ui-monospace, monospace; max-width: 280px;
  }}
  #tooltip .val {{ font-weight: 600; font-size: 13px; }}
</style>
</head>
<body>
<div class="viz-root" data-palette="{ramp_json}">
  <h1>Loom — attention weights</h1>
  <div class="subtitle">Real attention matrices captured from a forward pass on the prompt below.</div>
  <div class="config">{config_str}</div>
  <div class="subtitle" style="margin-top:4px;">Prompt: &ldquo;{prompt_escaped}&rdquo;</div>
  <div class="prompt-box" id="promptBox"></div>
  <div class="picker-row">
    <div class="picker-group"><span class="picker-label">Layer</span><span id="layerPicker"></span></div>
    <div class="picker-group"><span class="picker-label">Head</span><span id="headPicker"></span></div>
  </div>
  <div class="chart-card">
    <div id="grid"></div>
    <div class="legend">
      <span>0</span>
      <span class="ramp" id="legendRamp"></span>
      <span>1 (attention weight)</span>
      <span style="margin-left:16px; display:inline-flex; align-items:center; gap:6px;">
        <span style="width:12px;height:12px;background:var(--mask-fill);border:1px solid var(--gridline);display:inline-block;border-radius:2px;"></span>
        masked (future token, causal)
      </span>
    </div>
  </div>
</div>
<div id="tooltip"></div>
<script>
const DATA = {payload_json};
const RAMP = {ramp_json};

function lerpColor(a, b, t) {{
  const pa = [1,3,5].map(i => parseInt(a.substr(i,2), 16));
  const pb = [1,3,5].map(i => parseInt(b.substr(i,2), 16));
  const c = pa.map((v, i) => Math.round(v + (pb[i] - v) * t));
  return `rgb(${{c[0]}},${{c[1]}},${{c[2]}})`;
}}
function rampColor(t) {{
  t = Math.max(0, Math.min(1, t));
  const n = RAMP.length - 1;
  const pos = t * n;
  const i = Math.min(n - 1, Math.floor(pos));
  return lerpColor(RAMP[i], RAMP[i + 1], pos - i);
}}

let layer = 0, head = 0;

function buildPicker(el, count, label, onPick, current) {{
  el.textContent = "";
  for (let i = 0; i < count; i++) {{
    const b = document.createElement("button");
    b.className = "pick";
    b.type = "button";
    b.textContent = String(i);
    b.setAttribute("aria-pressed", i === current ? "true" : "false");
    b.setAttribute("aria-label", `${{label}} ${{i}}`);
    b.addEventListener("click", () => onPick(i));
    el.appendChild(b);
  }}
}}

function render() {{
  buildPicker(document.getElementById("layerPicker"), DATA.n_layer, "layer", (i) => {{ layer = i; render(); }}, layer);
  buildPicker(document.getElementById("headPicker"), DATA.n_head, "head", (i) => {{ head = i; render(); }}, head);

  const promptBox = document.getElementById("promptBox");
  promptBox.textContent = "";
  DATA.tokens.forEach((tk) => {{
    const span = document.createElement("span");
    span.textContent = tk;
    span.style.padding = "1px 2px";
    promptBox.appendChild(span);
  }});

  const matrix = DATA.data[layer][head];
  const grid = document.getElementById("grid");
  grid.textContent = "";
  const table = document.createElement("table");
  table.className = "heat";

  const headRow = document.createElement("tr");
  headRow.appendChild(document.createElement("th"));
  DATA.tokens.forEach((tk) => {{
    const th = document.createElement("th");
    th.textContent = tk;
    headRow.appendChild(th);
  }});
  table.appendChild(headRow);

  for (let qi = 0; qi < DATA.T; qi++) {{
    const row = document.createElement("tr");
    const rh = document.createElement("th");
    rh.className = "rowhead";
    rh.textContent = DATA.tokens[qi];
    row.appendChild(rh);
    for (let ki = 0; ki < DATA.T; ki++) {{
      const td = document.createElement("td");
      td.className = "cell";
      const masked = ki > qi;
      if (masked) {{
        td.classList.add("masked");
      }} else {{
        const w = matrix[qi][ki];
        td.style.background = rampColor(w);
        td.tabIndex = 0;
        const showTip = (evt) => {{
          const tip = document.getElementById("tooltip");
          tip.style.display = "block";
          tip.innerHTML = "";
          const valEl = document.createElement("div");
          valEl.className = "val";
          valEl.textContent = w.toFixed(4);
          const labelEl = document.createElement("div");
          labelEl.textContent = `query "${{DATA.tokens[qi]}}" -> key "${{DATA.tokens[ki]}}"`;
          tip.appendChild(valEl);
          tip.appendChild(labelEl);
          const x = evt.clientX, y = evt.clientY;
          tip.style.left = (x + 14) + "px";
          tip.style.top = (y + 14) + "px";
        }};
        td.addEventListener("pointermove", showTip);
        td.addEventListener("focus", (e) => showTip({{clientX: e.target.getBoundingClientRect().right, clientY: e.target.getBoundingClientRect().top}}));
        td.addEventListener("pointerleave", () => {{ document.getElementById("tooltip").style.display = "none"; }});
        td.addEventListener("blur", () => {{ document.getElementById("tooltip").style.display = "none"; }});
      }}
      row.appendChild(td);
    }}
    table.appendChild(row);
  }}
  grid.appendChild(table);

  const legendRamp = document.getElementById("legendRamp");
  legendRamp.style.background = `linear-gradient(to right, ${{RAMP.join(",")}})`;
}}

render();
</script>
</body>
</html>
"""

_TEMPLATE = _TEMPLATE.replace("{active_hue}", "#2a78d6")
