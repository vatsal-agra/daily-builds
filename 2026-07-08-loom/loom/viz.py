"""Renders a self-contained interactive HTML page that replays a REAL
generation from a trained checkpoint: per-layer, per-head attention-weight
heatmaps over the actual token stream, scrubbable step by step.

This is not a mockup -- the attention weights embedded in the page are
captured from the model's own forward pass (via a small monkey-patch on
CausalSelfAttention.forward that records the softmax output) while it
generates the exact text shown.
"""
import argparse
import json
import os

import numpy as np

from .generate import load_generator
from .tensor import no_grad


def _capture_generation(model, tok, prompt, max_new_tokens, temperature, top_k, seed):
    """Runs ordinary (non-KV-cached) generation -- so every step's forward
    pass recomputes full attention over the whole sequence so far, which is
    exactly what we want to record -- and reads each block's real attention
    weights (`last_attn`, stashed by CausalSelfAttention.forward as a normal
    side effect of the actual forward pass) after every step."""
    rng = np.random.default_rng(seed)
    prompt_ids = tok.encode(prompt) or [0]
    idx = np.array([prompt_ids], dtype=np.int64)
    max_new_tokens = max(0, min(max_new_tokens, model.block_size - idx.shape[1]))

    captured = []  # one entry per generation step: list of (1,n_head,T,T) arrays, one per layer
    with no_grad():
        for _ in range(max_new_tokens):
            logits, _ = model(idx)
            captured.append([block.attn.last_attn for block in model.blocks])
            last = logits.data[:, -1, :] / max(temperature, 1e-8)
            if top_k is not None:
                kk = min(top_k, last.shape[-1])
                kth = np.partition(last, -kk, axis=-1)[:, -kk:].min(axis=-1, keepdims=True)
                last = np.where(last < kth, -np.inf, last)
            m = last.max(axis=-1, keepdims=True)
            probs = np.exp(last - m)
            probs /= probs.sum(axis=-1, keepdims=True)
            next_tok = int(rng.choice(probs.shape[-1], p=probs[0]))
            idx = np.concatenate([idx, [[next_tok]]], axis=1)

    return idx[0].tolist(), captured


def render_html(tok, token_ids, attn_steps, prompt_len, n_layer, n_head):
    """attn_steps[i] is a list (len n_layer) of (1, n_head, T_i, T_i) arrays,
    for the i-th generated token (T_i = prompt_len + i, the length of the
    sequence BEFORE that token was appended)."""
    token_strs = [tok.decode([t]) for t in token_ids]

    steps_json = []
    for i, layers in enumerate(attn_steps):
        layer_data = []
        for layer_attn in layers:
            # (1, n_head, T, T) -> list of n_head TxT matrices. Rounded to
            # 3 decimal places: a heatmap only needs ~3 significant digits,
            # and full float64 precision roughly triples the embedded JSON
            # size (and thus the HTML file) for no visible benefit.
            heads = np.round(layer_attn[0], 3).tolist()
            layer_data.append(heads)
        steps_json.append({"generated_index": prompt_len + i, "layers": layer_data})

    data = {
        "tokens": token_strs,
        "prompt_len": prompt_len,
        "n_layer": n_layer,
        "n_head": n_head,
        "steps": steps_json,
    }

    html = HTML_TEMPLATE.replace("__DATA_JSON__", json.dumps(data))
    return html


HTML_TEMPLATE = r"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Loom -- Attention Visualizer</title>
<style>
  :root { color-scheme: light dark; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    margin: 0; padding: 24px; background: #0f1115; color: #e8e8ec;
    display: flex; flex-direction: column; align-items: center; gap: 18px;
  }
  @media (prefers-color-scheme: light) {
    body { background: #f7f7f9; color: #1a1a1f; }
  }
  h1 { font-size: 1.3rem; font-weight: 600; margin: 0; }
  .sub { opacity: 0.65; font-size: 0.85rem; margin-top: -12px; }
  #tokens {
    max-width: 900px; line-height: 2.1; font-size: 1.05rem; font-family: ui-monospace, monospace;
    padding: 16px; border-radius: 10px; background: rgba(127,127,127,0.08);
  }
  .tok { padding: 1px 2px; border-radius: 3px; cursor: pointer; white-space: pre; }
  .tok.prompt { opacity: 0.55; }
  .tok.current { outline: 2px solid #6ea8fe; }
  .controls { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; justify-content: center; }
  button { background: #2a2d36; color: inherit; border: 1px solid rgba(127,127,127,0.35);
    border-radius: 6px; padding: 6px 12px; cursor: pointer; font-size: 0.9rem; }
  button:hover { background: #363a45; }
  input[type=range] { width: 260px; }
  select { background: #2a2d36; color: inherit; border: 1px solid rgba(127,127,127,0.35); border-radius: 6px; padding: 4px 8px; }
  #heatmaps { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 14px; max-width: 900px; width: 100%; }
  .head-card { background: rgba(127,127,127,0.08); border-radius: 8px; padding: 8px; }
  .head-title { font-size: 0.75rem; opacity: 0.7; margin-bottom: 4px; text-align: center; }
  canvas { display: block; width: 100%; image-rendering: pixelated; border-radius: 4px; }
  #stepLabel { font-variant-numeric: tabular-nums; min-width: 90px; text-align: center; }
</style>
</head>
<body>
  <h1>Loom &mdash; Attention Visualizer</h1>
  <div class="sub">Real attention weights from a real trained checkpoint, captured during actual generation.</div>
  <div id="tokens"></div>
  <div class="controls">
    <button id="prevBtn">&larr; prev token</button>
    <span id="stepLabel">-</span>
    <button id="nextBtn">next token &rarr;</button>
    <button id="playBtn">&#9654; play</button>
    <label>layer <select id="layerSel"></select></label>
  </div>
  <div id="heatmaps"></div>

<script>
const DATA = __DATA_JSON__;
let stepIdx = 0;
let playing = false;
let playTimer = null;

const tokensEl = document.getElementById('tokens');
const stepLabel = document.getElementById('stepLabel');
const layerSel = document.getElementById('layerSel');
const heatmapsEl = document.getElementById('heatmaps');

for (let l = 0; l < DATA.n_layer; l++) {
  const opt = document.createElement('option');
  opt.value = l; opt.textContent = 'layer ' + l;
  layerSel.appendChild(opt);
}

function renderTokens() {
  tokensEl.innerHTML = '';
  const step = DATA.steps[stepIdx];
  const upto = step.generated_index; // index of the token just generated at this step
  for (let i = 0; i <= upto; i++) {
    const span = document.createElement('span');
    span.className = 'tok' + (i < DATA.prompt_len ? ' prompt' : '') + (i === upto ? ' current' : '');
    span.textContent = DATA.tokens[i];
    tokensEl.appendChild(span);
  }
}

function colorFor(v) {
  // v in [0,1] -> a blue-ish heat scale
  const t = Math.max(0, Math.min(1, v));
  const r = Math.round(20 + t * 235);
  const g = Math.round(30 + t * 120);
  const b = Math.round(80 + t * 100 * (1 - t) + 60);
  return `rgb(${r},${g},${b})`;
}

function renderHeatmaps() {
  heatmapsEl.innerHTML = '';
  const step = DATA.steps[stepIdx];
  const layer = parseInt(layerSel.value, 10);
  const heads = step.layers[layer]; // n_head arrays of TxT
  heads.forEach((matrix, h) => {
    const card = document.createElement('div');
    card.className = 'head-card';
    const title = document.createElement('div');
    title.className = 'head-title';
    title.textContent = 'head ' + h;
    card.appendChild(title);
    const T = matrix.length;
    const canvas = document.createElement('canvas');
    canvas.width = T; canvas.height = T;
    canvas.style.aspectRatio = '1 / 1';
    const ctx = canvas.getContext('2d');
    const img = ctx.createImageData(T, T);
    for (let i = 0; i < T; i++) {
      for (let j = 0; j < T; j++) {
        const v = matrix[i][j];
        const col = colorFor(v);
        const m = col.match(/\d+/g).map(Number);
        const idx = (i * T + j) * 4;
        img.data[idx] = m[0]; img.data[idx+1] = m[1]; img.data[idx+2] = m[2]; img.data[idx+3] = 255;
      }
    }
    ctx.putImageData(img, 0, 0);
    card.appendChild(canvas);
    heatmapsEl.appendChild(card);
  });
}

function render() {
  stepLabel.textContent = (stepIdx + 1) + ' / ' + DATA.steps.length;
  renderTokens();
  renderHeatmaps();
}

document.getElementById('prevBtn').onclick = () => {
  stepIdx = Math.max(0, stepIdx - 1);
  render();
};
document.getElementById('nextBtn').onclick = () => {
  stepIdx = Math.min(DATA.steps.length - 1, stepIdx + 1);
  render();
};
layerSel.onchange = render;

document.getElementById('playBtn').onclick = (e) => {
  playing = !playing;
  e.target.textContent = playing ? '⏸ pause' : '▶ play';
  if (playing) {
    playTimer = setInterval(() => {
      stepIdx = (stepIdx + 1) % DATA.steps.length;
      render();
    }, 450);
  } else {
    clearInterval(playTimer);
  }
};

render();
</script>
</body>
</html>
"""


def build_argparser():
    p = argparse.ArgumentParser(description="Render an interactive attention visualizer HTML page.")
    p.add_argument("--checkpoint-dir", default=os.path.join(os.path.dirname(__file__), "..", "checkpoints"))
    p.add_argument("--prompt", default="Long ago, in the Whispering Forest,")
    p.add_argument("--max-new-tokens", type=int, default=24)
    p.add_argument("--temperature", type=float, default=0.8)
    p.add_argument("--top-k", type=int, default=40)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "..", "attention_viz.html"))
    return p


def main(argv=None):
    ns = build_argparser().parse_args(argv)
    model, tok, config = load_generator(ns.checkpoint_dir)
    token_ids, attn_steps = _capture_generation(
        model, tok, ns.prompt, ns.max_new_tokens, ns.temperature, ns.top_k, ns.seed
    )
    prompt_len = len(tok.encode(ns.prompt) or [0])
    html = render_html(tok, token_ids, attn_steps, prompt_len, config["n_layer"], config["n_head"])
    with open(ns.out, "w") as f:
        f.write(html)
    print(f"wrote {ns.out} ({len(attn_steps)} generation steps captured)")


if __name__ == "__main__":
    main()
