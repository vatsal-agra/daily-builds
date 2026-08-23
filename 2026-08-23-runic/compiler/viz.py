"""
Generates a single self-contained HTML step-through debugger for a Runic
function call: operand stack, locals, call-frame depth, linear memory (if
the module has any), and the current instruction, one step at a time.

The trace is collected by running the *real* interpreter (interpreter.py)
with its trace_hook — so what you see stepping through is exactly what
actually executed, not a simulation of it.
"""

import json

from .interpreter import Instance

MAX_STEPS = 4000
DEFAULT_MEM_BYTES_SHOWN = 256


def collect_trace(wasm_bytes, func_name, args, mem_hint_bytes=None):
    inst = Instance(wasm_bytes)
    func_names_by_idx = {idx: name for name, (kind, idx) in inst.exports.items() if kind == 0}

    # How much of linear memory is worth showing: the caller (cli.py) can
    # pass the program's actual declared-array footprint; otherwise fall
    # back to a small default so a huge unused wasm page doesn't bloat the
    # trace with thousands of zero bytes per step.
    mem_bytes_to_show = mem_hint_bytes if mem_hint_bytes else DEFAULT_MEM_BYTES_SHOWN
    if inst.memory is not None:
        mem_bytes_to_show = min(mem_bytes_to_show, len(inst.memory.data))

    steps = []
    truncated = [False]

    def hook(funcidx, pc, op, imm, stack, locals_, depth):
        if len(steps) >= MAX_STEPS:
            truncated[0] = True
            return
        mem_snapshot = None
        if inst.memory is not None:
            mem_snapshot = list(inst.memory.data[:mem_bytes_to_show])
        imm_out = list(imm) if isinstance(imm, tuple) else imm
        steps.append({
            "fn": func_names_by_idx.get(funcidx, f"f{funcidx}"),
            "pc": pc,
            "op": op,
            "imm": imm_out,
            "stack": list(stack),
            "locals": list(locals_),
            "depth": depth,
            "mem": mem_snapshot,
        })

    inst.trace_hook = hook
    trap = None
    result = None
    try:
        result = inst.call_by_name(func_name, args)
    except Exception as e:  # noqa: BLE001 - surfaced to the visualizer, not swallowed
        trap = str(e)

    return {
        "steps": steps,
        "result": result,
        "trap": trap,
        "truncated": truncated[0],
        "hasMemory": inst.memory is not None,
    }


PAGE_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Runic — {FUNC_NAME}({ARGS_STR}) trace</title>
<style>
  :root {
    --bg: #0d1117; --panel: #161b22; --border: #30363d; --text: #e6edf3;
    --muted: #8b949e; --accent: #58a6ff; --accent2: #d29922; --good: #3fb950;
    --bad: #f85149; --stack-fill: #1f6feb;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--bg); color: var(--text);
    font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
    font-size: 14px;
  }
  header {
    padding: 18px 24px; border-bottom: 1px solid var(--border);
    display: flex; align-items: baseline; gap: 14px; flex-wrap: wrap;
  }
  header h1 { font-size: 17px; margin: 0; letter-spacing: 0.5px; }
  header .sub { color: var(--muted); font-size: 13px; }
  .layout {
    display: grid; grid-template-columns: 1fr 320px; gap: 16px;
    padding: 20px 24px; max-width: 1400px; margin: 0 auto;
  }
  @media (max-width: 900px) { .layout { grid-template-columns: 1fr; } }
  .panel {
    background: var(--panel); border: 1px solid var(--border); border-radius: 10px;
    padding: 16px; margin-bottom: 16px;
  }
  .panel h2 {
    font-size: 12px; text-transform: uppercase; letter-spacing: 1px;
    color: var(--muted); margin: 0 0 12px 0; font-weight: 600;
  }
  .controls { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
  button {
    background: #21262d; color: var(--text); border: 1px solid var(--border);
    border-radius: 6px; padding: 7px 14px; font: inherit; cursor: pointer;
  }
  button:hover:not(:disabled) { background: #30363d; border-color: var(--accent); }
  button:disabled { opacity: 0.35; cursor: default; }
  button.primary { background: var(--accent); color: #0d1117; border-color: var(--accent); font-weight: 600; }
  button.primary:hover { filter: brightness(1.1); }
  input[type=range] { flex: 1; min-width: 120px; accent-color: var(--accent); }
  .step-counter { color: var(--muted); min-width: 110px; text-align: right; }
  .code-view {
    max-height: 420px; overflow-y: auto; border: 1px solid var(--border);
    border-radius: 8px; background: #010409;
  }
  .code-line {
    display: flex; gap: 10px; padding: 3px 12px; white-space: pre;
    color: #6e7681;
  }
  .code-line .pc { color: #484f58; width: 34px; flex: none; text-align: right; }
  .code-line.current { background: rgba(88,166,255,0.18); color: var(--text); }
  .code-line.current .pc { color: var(--accent); font-weight: 700; }
  .code-line .op { color: #79c0ff; }
  .code-line.current .op { color: var(--accent); }
  .code-line .imm { color: var(--accent2); }
  .stack-view { display: flex; flex-direction: column-reverse; gap: 4px; min-height: 40px; }
  .stack-cell {
    background: var(--stack-fill); color: white; border-radius: 6px;
    padding: 6px 10px; font-weight: 600; display: flex; justify-content: space-between;
  }
  .stack-cell .idx { opacity: 0.6; font-weight: 400; font-size: 11px; }
  .empty-note { color: var(--muted); font-style: italic; font-size: 13px; }
  table.locals { width: 100%; border-collapse: collapse; }
  table.locals td { padding: 4px 6px; border-bottom: 1px solid var(--border); }
  table.locals td:first-child { color: var(--muted); }
  table.locals td:last-child { text-align: right; font-weight: 600; color: var(--accent2); }
  .callstack { display: flex; flex-direction: column; gap: 3px; }
  .callstack .frame {
    padding: 4px 8px; border-left: 3px solid var(--accent); border-radius: 3px;
    background: rgba(88,166,255,0.08); font-size: 12px;
  }
  .mem-grid {
    display: grid; grid-template-columns: repeat(16, 1fr); gap: 2px;
    font-size: 10px; max-height: 240px; overflow-y: auto;
  }
  .mem-byte {
    background: #0d1117; border: 1px solid var(--border); text-align: center;
    padding: 3px 0; border-radius: 3px; color: var(--muted);
  }
  .mem-byte.nonzero { background: #1f6feb33; color: var(--text); border-color: var(--accent); }
  .result-banner {
    padding: 12px 16px; border-radius: 8px; font-weight: 600; margin-bottom: 16px;
    display: flex; justify-content: space-between; align-items: center;
  }
  .result-banner.ok { background: rgba(63,185,80,0.12); border: 1px solid var(--good); color: var(--good); }
  .result-banner.trap { background: rgba(248,81,73,0.12); border: 1px solid var(--bad); color: var(--bad); }
  footer { text-align: center; color: var(--muted); padding: 24px; font-size: 12px; }
  a { color: var(--accent); }
</style>
</head>
<body>
<header>
  <h1>⚙ Runic step-through debugger</h1>
  <div class="sub">{FUNC_NAME}({ARGS_STR}) — {STEP_COUNT} instructions traced{TRUNC_NOTE}</div>
</header>
<div class="layout">
  <div>
    <div class="panel">
      <h2>Controls</h2>
      <div class="controls">
        <button id="btnReset" title="Reset to start">⏮</button>
        <button id="btnPrev" title="Step back">◀ Step</button>
        <button id="btnPlay" class="primary" title="Play / Pause">▶ Play</button>
        <button id="btnNext" title="Step forward">Step ▶</button>
        <button id="btnEnd" title="Jump to end">⏭</button>
        <input type="range" id="slider" min="0" max="{MAX_INDEX}" value="0">
        <span class="step-counter" id="stepCounter">step 0 / {MAX_INDEX}</span>
      </div>
    </div>

    <div id="resultBanner"></div>

    <div class="panel">
      <h2>Instructions (function: <span id="curFnName">—</span>)</h2>
      <div class="code-view" id="codeView"></div>
    </div>

    <div class="panel" id="memPanel" style="display:none">
      <h2>Linear memory (first bytes, grouped as i32 grid; highlighted = nonzero)</h2>
      <div class="mem-grid" id="memGrid"></div>
    </div>
  </div>

  <div>
    <div class="panel">
      <h2>Operand stack (top first)</h2>
      <div class="stack-view" id="stackView"></div>
    </div>
    <div class="panel">
      <h2>Locals</h2>
      <table class="locals" id="localsTable"></table>
    </div>
    <div class="panel">
      <h2>Call depth</h2>
      <div class="callstack" id="callstackView"></div>
    </div>
  </div>
</div>
<footer>Runic — a from-scratch WebAssembly toolchain. Trace generated by compiler/interpreter.py's own trace_hook — this is the real execution, not a re-simulation.</footer>

<script>
const TRACE = {TRACE_JSON};
const steps = TRACE.steps;
let idx = 0;
let playing = false;
let playTimer = null;

const codeView = document.getElementById('codeView');
const stackView = document.getElementById('stackView');
const localsTable = document.getElementById('localsTable');
const callstackView = document.getElementById('callstackView');
const memPanel = document.getElementById('memPanel');
const memGrid = document.getElementById('memGrid');
const slider = document.getElementById('slider');
const stepCounter = document.getElementById('stepCounter');
const curFnName = document.getElementById('curFnName');
const resultBanner = document.getElementById('resultBanner');

function fmtImm(op, imm) {
  if (imm === null || imm === undefined) return '';
  if (Array.isArray(imm)) return `offset=${imm[1]} align=${imm[0]}`;
  return String(imm);
}

function render() {
  const s = steps[idx];
  if (!s) return;
  stepCounter.textContent = `step ${idx} / ${steps.length - 1}`;
  slider.value = idx;
  curFnName.textContent = s.fn;

  // code view: show a window of instructions around current pc from the SAME function run
  // (we only have the flat trace, so show the last N steps of this function call as a scroll log)
  let windowStart = idx;
  while (windowStart > 0 && steps[windowStart - 1].fn === s.fn && steps[windowStart - 1].pc < s.pc && (idx - windowStart) < 40) windowStart--;
  codeView.innerHTML = '';
  const lo = Math.max(0, idx - 25), hi = Math.min(steps.length, idx + 6);
  for (let i = lo; i < hi; i++) {
    const st = steps[i];
    const div = document.createElement('div');
    div.className = 'code-line' + (i === idx ? ' current' : '');
    div.innerHTML = `<span class="pc">${st.pc}</span><span class="op">${st.op}</span><span class="imm">${fmtImm(st.op, st.imm)}</span>` +
                     (st.fn !== s.fn ? ` <span style="color:#484f58">(${st.fn})</span>` : '');
    codeView.appendChild(div);
    if (i === idx) setTimeout(() => div.scrollIntoView({block: 'center'}), 0);
  }

  stackView.innerHTML = '';
  if (s.stack.length === 0) {
    stackView.innerHTML = '<div class="empty-note">(empty)</div>';
  } else {
    for (let i = s.stack.length - 1; i >= 0; i--) {
      const cell = document.createElement('div');
      cell.className = 'stack-cell';
      cell.innerHTML = `<span>${s.stack[i]}</span><span class="idx">#${i}</span>`;
      stackView.appendChild(cell);
    }
  }

  localsTable.innerHTML = '';
  s.locals.forEach((v, i) => {
    const tr = document.createElement('tr');
    tr.innerHTML = `<td>local ${i}</td><td>${v}</td>`;
    localsTable.appendChild(tr);
  });
  if (s.locals.length === 0) localsTable.innerHTML = '<tr><td class="empty-note">(none)</td></tr>';

  callstackView.innerHTML = '';
  for (let d = 1; d <= s.depth; d++) {
    const div = document.createElement('div');
    div.className = 'frame';
    div.style.marginLeft = ((d - 1) * 14) + 'px';
    div.textContent = d === s.depth ? `→ ${s.fn} (depth ${d})` : `… (depth ${d})`;
    callstackView.appendChild(div);
  }
  if (s.depth === 0) callstackView.innerHTML = '<div class="empty-note">(no active call)</div>';

  if (s.mem) {
    memPanel.style.display = '';
    memGrid.innerHTML = '';
    const words = [];
    for (let i = 0; i < s.mem.length; i += 4) {
      words.push(s.mem[i] | (s.mem[i+1] << 8) | (s.mem[i+2] << 16) | (s.mem[i+3] << 24));
    }
    words.forEach((w, i) => {
      const cell = document.createElement('div');
      cell.className = 'mem-byte' + (w !== 0 ? ' nonzero' : '');
      cell.title = `byte offset ${i * 4}`;
      cell.textContent = w;
      memGrid.appendChild(cell);
    });
  } else {
    memPanel.style.display = 'none';
  }

  const isLast = idx === steps.length - 1;
  resultBanner.innerHTML = '';
  if (isLast) {
    const div = document.createElement('div');
    if (TRACE.trap) {
      div.className = 'result-banner trap';
      div.innerHTML = `<span>⚠ trapped</span><span>${TRACE.trap}</span>`;
    } else {
      div.className = 'result-banner ok';
      div.innerHTML = `<span>✓ returned</span><span>${TRACE.result}</span>`;
    }
    resultBanner.appendChild(div);
  }

  document.getElementById('btnPrev').disabled = idx === 0;
  document.getElementById('btnNext').disabled = idx === steps.length - 1;
  document.getElementById('btnEnd').disabled = idx === steps.length - 1;
}

function step(delta) {
  idx = Math.max(0, Math.min(steps.length - 1, idx + delta));
  render();
}

document.getElementById('btnPrev').onclick = () => step(-1);
document.getElementById('btnNext').onclick = () => step(1);
document.getElementById('btnReset').onclick = () => { idx = 0; render(); };
document.getElementById('btnEnd').onclick = () => { idx = steps.length - 1; render(); };
slider.oninput = (e) => { idx = parseInt(e.target.value, 10); render(); };
document.getElementById('btnPlay').onclick = (e) => {
  playing = !playing;
  e.target.textContent = playing ? '⏸ Pause' : '▶ Play';
  if (playing) {
    playTimer = setInterval(() => {
      if (idx >= steps.length - 1) { playing = false; e.target.textContent = '▶ Play'; clearInterval(playTimer); return; }
      step(1);
    }, 90);
  } else {
    clearInterval(playTimer);
  }
};

render();
</script>
</body>
</html>
"""


def generate_html(wasm_bytes, func_name, args, mem_hint_bytes=None):
    trace = collect_trace(wasm_bytes, func_name, args, mem_hint_bytes=mem_hint_bytes)
    args_str = ", ".join(str(a) for a in args)
    trunc_note = " (truncated — trace exceeded the step limit)" if trace["truncated"] else ""

    html = PAGE_TEMPLATE
    html = html.replace("{FUNC_NAME}", func_name)
    html = html.replace("{ARGS_STR}", args_str)
    html = html.replace("{STEP_COUNT}", str(len(trace["steps"])))
    html = html.replace("{TRUNC_NOTE}", trunc_note)
    html = html.replace("{MAX_INDEX}", str(max(0, len(trace["steps"]) - 1)))
    html = html.replace("{TRACE_JSON}", json.dumps(trace))
    return html
