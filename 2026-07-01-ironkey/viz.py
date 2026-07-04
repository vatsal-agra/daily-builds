"""
Generates a single self-contained HTML file that animates two real
from-scratch computations byte-by-byte / round-by-round:

  1. AES-256 encrypting one 16-byte block — every SubBytes, ShiftRows,
     MixColumns, and AddRoundKey output, as an actual 4x4 state grid.
  2. SHA-256 compressing its first 512-bit block — the eight working
     registers (a..h) after each of the 64 rounds.

All of the data embedded in the page comes directly from `aes.trace_encrypt`
and `sha256.trace_compress_first_block` — this is not a separate JS
reimplementation that could drift from the real algorithm, it's a
recording of it.
"""
import json

import aes
import sha256 as sha256_mod

_DEFAULT_KEY = bytes(range(32))  # 00 01 02 .. 1f — deterministic, no hidden randomness
_DEFAULT_AES_TEXT = b"Ironkey demo!!!!"  # exactly 16 bytes
_DEFAULT_SHA_TEXT = b"Ironkey from-scratch cryptography suite"


def _state_hex_rows(state_bytes):
    """Format 16 bytes as the 4x4 column-major AES state grid (row r,
    col c -> byte index r + 4c), returned as 4 rows of 4 hex bytes."""
    return [[f"{state_bytes[r + 4 * c]:02x}" for c in range(4)] for r in range(4)]


def build_aes_trace(key, plaintext):
    if len(plaintext) != 16:
        raise ValueError("AES visualizer needs exactly 16 bytes of plaintext (one block)")
    steps = aes.trace_encrypt(plaintext, key)
    return [{"label": label, "grid": _state_hex_rows(state), "hex": state.hex()} for label, state in steps]


def build_sha_trace(message):
    trace = sha256_mod.trace_compress_first_block(message)
    steps = [
        {
            "round": s["round"],
            "regs": [f"{s[r]:08x}" for r in "abcdefgh"],
            "w": None if s["w"] is None else f"{s['w']:08x}",
        }
        for s in trace["steps"]
    ]
    return {
        "steps": steps,
        "w_schedule": [f"{w:08x}" for w in trace["w"]],
        # The real full-message digest (correct even across multiple
        # blocks) — distinct from `trace["final_words"]`, which is only
        # the state after compressing block 1 and would be wrong to show
        # as "the digest" whenever the message needs more than one block.
        "final_hash": sha256_mod.sha256_hex(message),
        "is_only_block": trace["is_only_block"],
        "total_blocks": trace["total_blocks"],
        "message_preview": message.decode("utf-8", errors="replace"),
    }


_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Ironkey — AES &amp; SHA-256 visualizer</title>
<style>
  :root {
    --bg: #0b0f14; --panel: #121821; --panel2: #1a2230; --border: #26313f;
    --text: #dbe4ee; --dim: #7f8ea3; --accent: #4fd1c5; --accent2: #f5a623;
    --changed: #f5563155; --changed-border: #f55631;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 32px 24px 64px; background: var(--bg); color: var(--text);
    font-family: 'SF Mono', 'Fira Code', Menlo, Consolas, monospace;
  }
  h1 { font-size: 20px; margin: 0 0 4px; font-weight: 600; letter-spacing: 0.02em; }
  .subtitle { color: var(--dim); font-size: 13px; margin-bottom: 24px; }
  .tabs { display: flex; gap: 8px; margin-bottom: 20px; }
  .tab-btn {
    background: var(--panel); border: 1px solid var(--border); color: var(--dim);
    padding: 8px 18px; border-radius: 8px; cursor: pointer; font: inherit; font-size: 13px;
  }
  .tab-btn.active { color: var(--bg); background: var(--accent); border-color: var(--accent); font-weight: 600; }
  .panel { display: none; }
  .panel.active { display: block; }
  .card {
    background: var(--panel); border: 1px solid var(--border); border-radius: 12px;
    padding: 20px 24px; margin-bottom: 16px;
  }
  .meta { color: var(--dim); font-size: 12px; margin-bottom: 14px; line-height: 1.6; }
  .meta b { color: var(--text); }
  .controls { display: flex; align-items: center; gap: 12px; margin-bottom: 18px; flex-wrap: wrap; }
  button.step {
    background: var(--panel2); border: 1px solid var(--border); color: var(--text);
    padding: 8px 16px; border-radius: 8px; cursor: pointer; font: inherit; font-size: 13px;
  }
  button.step:hover { border-color: var(--accent); color: var(--accent); }
  button.step:disabled { opacity: 0.35; cursor: default; }
  input[type=range] { flex: 1; min-width: 160px; accent-color: var(--accent); }
  .step-label { font-size: 14px; color: var(--accent2); font-weight: 600; min-width: 220px; }
  .step-count { color: var(--dim); font-size: 12px; }
  .grid4 { display: grid; grid-template-columns: repeat(4, 64px); gap: 6px; margin: 16px 0; }
  .cell {
    background: var(--panel2); border: 1px solid var(--border); border-radius: 6px;
    text-align: center; padding: 10px 0; font-size: 15px; transition: background 0.15s, border-color 0.15s;
  }
  .cell.changed { background: var(--changed); border-color: var(--changed-border); color: #ffd8cf; }
  .hexline { color: var(--dim); font-size: 12px; margin-top: 4px; word-break: break-all; }
  .regs { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin: 16px 0; max-width: 640px; }
  .reg { background: var(--panel2); border: 1px solid var(--border); border-radius: 8px; padding: 10px; text-align: center; }
  .reg .name { color: var(--dim); font-size: 11px; }
  .reg .val { font-size: 15px; margin-top: 4px; transition: background 0.15s; border-radius: 4px; }
  .reg .val.changed { background: var(--changed); color: #ffd8cf; }
  .wval { color: var(--accent); font-size: 13px; margin-top: 6px; }
  .footer-note { color: var(--dim); font-size: 11px; margin-top: 8px; }
  kbd {
    background: var(--panel2); border: 1px solid var(--border); border-radius: 4px;
    padding: 1px 6px; font-size: 11px;
  }
</style>
</head>
<body>
  <h1>Ironkey — cryptographic step visualizer</h1>
  <div class="subtitle">Every value below comes from the real from-scratch implementation (aes.py / sha256.py) — this is a recording, not a re-implementation.</div>

  <div class="tabs">
    <button class="tab-btn active" data-tab="aes">AES-256 block encryption</button>
    <button class="tab-btn" data-tab="sha">SHA-256 compression (first block)</button>
  </div>

  <div id="tab-aes" class="panel active">
    <div class="card">
      <div class="meta">
        Key: <b>__AES_KEY_HEX__</b> (256-bit)<br>
        Plaintext block: <b>__AES_PT_HEX__</b> (<b>__AES_PT_TEXT__</b>)<br>
        Ciphertext: <b id="aes-final-hex"></b>
      </div>
      <div class="controls">
        <button class="step" id="aes-prev">&larr; Prev</button>
        <button class="step" id="aes-next">Next &rarr;</button>
        <input type="range" id="aes-slider" min="0" value="0">
        <span class="step-count" id="aes-count"></span>
      </div>
      <div class="step-label" id="aes-label"></div>
      <div class="grid4" id="aes-grid"></div>
      <div class="hexline" id="aes-hex"></div>
      <div class="footer-note">Grid is the AES state in column-major order (row r, column c is byte index r+4c). Bytes highlighted orange changed on this step. Use <kbd>&larr;</kbd>/<kbd>&rarr;</kbd> or the slider.</div>
    </div>
  </div>

  <div id="tab-sha" class="panel">
    <div class="card">
      <div class="meta">
        Message: <b>__SHA_TEXT__</b><br>
        Blocks after padding: <b>__SHA_BLOCKS__</b> (animating block 1 of __SHA_BLOCKS__)<br>
        Final digest (all blocks): <b>__SHA_FINAL__</b>
      </div>
      <div class="controls">
        <button class="step" id="sha-prev">&larr; Prev</button>
        <button class="step" id="sha-next">Next &rarr;</button>
        <input type="range" id="sha-slider" min="0" value="0">
        <span class="step-count" id="sha-count"></span>
      </div>
      <div class="step-label" id="sha-label"></div>
      <div class="regs" id="sha-regs"></div>
      <div class="wval" id="sha-w"></div>
      <div class="footer-note">Registers a..h after each of the 64 compression rounds of the first 512-bit block. <kbd>&larr;</kbd>/<kbd>&rarr;</kbd> or the slider step through rounds.</div>
    </div>
  </div>

<script>
const AES_TRACE = __AES_TRACE_JSON__;
const SHA_TRACE = __SHA_TRACE_JSON__;

function setupTabs() {
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
      btn.classList.add('active');
      document.getElementById('tab-' + btn.dataset.tab).classList.add('active');
    });
  });
}

function stepper(prefix, steps, render) {
  let i = 0;
  const slider = document.getElementById(prefix + '-slider');
  slider.max = steps.length - 1;
  const prevBtn = document.getElementById(prefix + '-prev');
  const nextBtn = document.getElementById(prefix + '-next');
  const countEl = document.getElementById(prefix + '-count');

  function show() {
    render(steps[i], i > 0 ? steps[i - 1] : null);
    slider.value = i;
    countEl.textContent = `step ${i + 1} / ${steps.length}`;
    prevBtn.disabled = i === 0;
    nextBtn.disabled = i === steps.length - 1;
  }
  prevBtn.addEventListener('click', () => { if (i > 0) { i--; show(); } });
  nextBtn.addEventListener('click', () => { if (i < steps.length - 1) { i++; show(); } });
  slider.addEventListener('input', () => { i = parseInt(slider.value, 10); show(); });
  return { show, next: () => { if (i < steps.length - 1) { i++; show(); } },
           prev: () => { if (i > 0) { i--; show(); } } };
}

function renderAesStep(step, prevStep) {
  document.getElementById('aes-label').textContent = step.label;
  document.getElementById('aes-hex').textContent = step.hex;
  const grid = document.getElementById('aes-grid');
  grid.innerHTML = '';
  for (let r = 0; r < 4; r++) {
    for (let c = 0; c < 4; c++) {
      const cell = document.createElement('div');
      cell.className = 'cell';
      cell.textContent = step.grid[r][c];
      if (prevStep && prevStep.grid[r][c] !== step.grid[r][c]) cell.classList.add('changed');
      grid.appendChild(cell);
    }
  }
}

function renderShaStep(step, prevStep) {
  document.getElementById('sha-label').textContent =
    step.round === -1 ? 'Initial hash value H(0)' : `Round ${step.round}`;
  document.getElementById('sha-w').textContent = step.w ? `W[${step.round}] = 0x${step.w}` : '';
  const names = ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'];
  const regsEl = document.getElementById('sha-regs');
  regsEl.innerHTML = '';
  names.forEach((name, idx) => {
    const box = document.createElement('div');
    box.className = 'reg';
    const changed = prevStep && prevStep.regs[idx] !== step.regs[idx];
    box.innerHTML = `<div class="name">${name}</div><div class="val${changed ? ' changed' : ''}">0x${step.regs[idx]}</div>`;
    regsEl.appendChild(box);
  });
}

setupTabs();
document.getElementById('aes-final-hex').textContent =
  '0x' + AES_TRACE[AES_TRACE.length - 1].hex;
const aesStepper = stepper('aes', AES_TRACE, renderAesStep);
const shaStepper = stepper('sha', SHA_TRACE.steps, renderShaStep);
aesStepper.show();
shaStepper.show();

document.addEventListener('keydown', (e) => {
  const activeTab = document.querySelector('.tab-btn.active').dataset.tab;
  const s = activeTab === 'aes' ? aesStepper : shaStepper;
  if (e.key === 'ArrowRight') s.next();
  if (e.key === 'ArrowLeft') s.prev();
});
</script>
</body>
</html>
"""


def generate_html(key=None, aes_text=None, sha_text=None):
    key = key if key is not None else _DEFAULT_KEY
    aes_text = aes_text if aes_text is not None else _DEFAULT_AES_TEXT
    sha_text = sha_text if sha_text is not None else _DEFAULT_SHA_TEXT

    if len(aes_text) < 16:
        aes_text = aes_text + b" " * (16 - len(aes_text))
    aes_text = aes_text[:16]

    aes_trace = build_aes_trace(key, aes_text)
    sha_trace = build_sha_trace(sha_text)

    html = _HTML_TEMPLATE
    html = html.replace("__AES_KEY_HEX__", key.hex())
    html = html.replace("__AES_PT_HEX__", aes_text.hex())
    html = html.replace("__AES_PT_TEXT__", aes_text.decode("utf-8", errors="replace"))
    html = html.replace("__SHA_TEXT__", sha_trace["message_preview"])
    html = html.replace("__SHA_BLOCKS__", str(sha_trace["total_blocks"]))
    html = html.replace("__SHA_FINAL__", sha_trace["final_hash"])
    html = html.replace("__AES_TRACE_JSON__", json.dumps(aes_trace))
    html = html.replace("__SHA_TRACE_JSON__", json.dumps(sha_trace))
    return html


def write_html(path, key=None, aes_text=None, sha_text=None):
    html = generate_html(key, aes_text, sha_text)
    with open(path, "w") as f:
        f.write(html)
    return path
