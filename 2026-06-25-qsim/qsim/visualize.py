"""
Visualization: ASCII circuit diagrams + interactive single-file HTML visualizer.

ASCII circuit:
  Each qubit gets a horizontal wire.  Gates are drawn as boxes.
  Two-qubit connections use vertical lines.

HTML visualizer:
  - SVG circuit diagram
  - Amplitude histogram with phase-colored bars
  - Bloch sphere (SVG) for each qubit's reduced state
  - Shot histogram
  - Step-through animation (apply gates one by one)
"""

import cmath
import math
import json
import html as html_mod
from .state import QuantumState
from .circuit import Circuit


# ------------------------------------------------------------------
# ASCII Circuit Renderer
# ------------------------------------------------------------------

def circuit_to_ascii(circuit: Circuit, max_width: int = 100) -> str:
    """
    Render a Circuit as ASCII art.

    Format:
      q0: ─H─────●─────
      q1: ───────X─────
      q2: ─H─────────M─

    Box characters: ─ │ ┼ ● ⊕ M
    """
    n = circuit.n
    # Separate instructions into columns (time steps)
    # A column can hold a gate if none of its qubits are already occupied
    columns = []
    qubit_col = [-1] * n  # last column each qubit was used in

    for instr in circuit._instructions:
        if instr.kind == "barrier":
            columns.append(("barrier", instr.qubits))
            for q in instr.qubits:
                qubit_col[q] = len(columns) - 1
            continue

        if instr.kind in ("gate", "measure", "reset"):
            qs = instr.qubits
            if instr.kind == "measure":
                qs = [instr.qubits[0]]
            # Find the earliest column where all qubits are free
            min_col = max((qubit_col[q] for q in qs), default=-1) + 1
            while len(columns) <= min_col:
                columns.append([])
            # Also check two-qubit span: qubits between control and target must be free
            if len(qs) >= 2:
                span = list(range(min(qs), max(qs) + 1))
                min_col = max(min_col,
                              max((qubit_col[q] for q in span), default=-1) + 1)
                while len(columns) <= min_col:
                    columns.append([])
            columns[min_col].append(instr)
            for q in qs:
                qubit_col[q] = min_col

    # Render each column
    # Wire: one row per qubit, "─" between gates
    WIRE = "─"
    lines = [f"q{q}: " for q in range(n)]

    for col_idx, col in enumerate(columns):
        if col == ("barrier", list(range(n))) or (
            isinstance(col, tuple) and col[0] == "barrier"
        ):
            for q in range(n):
                lines[q] += "║"
            continue

        if not col:
            for q in range(n):
                lines[q] += WIRE
            continue

        # Determine column width and symbols for each qubit
        symbols = ["─"] * n  # default: wire through
        connectors = [False] * n  # True = draw vertical connector ┼

        for instr in col:
            if instr.kind == "gate":
                label = _gate_label(instr.gate.name)
                qs = instr.qubits
                if len(qs) == 1:
                    symbols[qs[0]] = f"[{label}]"
                elif len(qs) == 2:
                    ctrl, tgt = qs[0], qs[1]
                    if instr.gate.name in ("CNOT", "CX"):
                        symbols[ctrl] = "[●]"
                        symbols[tgt] = "[⊕]"
                    elif instr.gate.name == "CZ":
                        symbols[ctrl] = "[●]"
                        symbols[tgt] = "[●]"
                    elif instr.gate.name == "SWAP":
                        symbols[ctrl] = "[×]"
                        symbols[tgt] = "[×]"
                    else:
                        symbols[ctrl] = f"[●]"
                        symbols[tgt] = f"[{label}]"
                    for q in range(min(ctrl, tgt) + 1, max(ctrl, tgt)):
                        connectors[q] = True
                elif len(qs) == 3:
                    symbols[qs[0]] = "[■]"
                    symbols[qs[1]] = "[■]"
                    symbols[qs[2]] = "[⊕]"
                    for q in range(min(qs), max(qs) + 1):
                        if symbols[q] == "─":
                            connectors[q] = True
                else:
                    for q in qs:
                        symbols[q] = f"[{label[:3]}]"
            elif instr.kind == "measure":
                symbols[instr.qubits[0]] = "[M]"
            elif instr.kind == "reset":
                symbols[instr.qubits[0]] = "[R]"

        # Compute column width
        col_width = max(len(s) for s in symbols)
        col_width = max(col_width, 3)

        for q in range(n):
            sym = symbols[q]
            if connectors[q] and sym == "─":
                sym = "[┼]"
            # Pad to col_width with wire characters
            padded = sym.center(col_width, "─")
            lines[q] += padded

    return "\n".join(lines)


def _gate_label(name: str) -> str:
    """Short label for ASCII display."""
    short = {
        "Toffoli": "CCX",
        "Fredkin": "CSW",
        "iSWAP": "iSW",
    }
    if name in short:
        return short[name]
    # Parameterized gates: truncate at first '('
    if "(" in name:
        return name[:name.index("(")]
    return name[:4] if len(name) > 4 else name


# ------------------------------------------------------------------
# HTML Visualizer
# ------------------------------------------------------------------

def build_html(circuit: Circuit, result=None, title: str = "QSim Visualizer") -> str:
    """
    Build a self-contained HTML visualizer for the circuit + result.

    Includes:
    - SVG circuit diagram
    - Amplitude histogram (phase-colored)
    - Bloch spheres for each qubit
    - Shot histogram (if multiple shots)
    - Step-through animation
    """
    state = result.final_state if result else None
    counts = result.counts if result else {}
    shots = result.shots if result else 0

    ascii_art = circuit_to_ascii(circuit)
    gate_data = _circuit_to_json(circuit)
    state_data = _state_to_json(state) if state else None
    counts_data = json.dumps(counts) if counts else "null"

    bloch_data = None
    if state:
        bvecs = []
        for q in range(min(state.n, 8)):
            x, y, z = state.bloch_vector(q)
            bvecs.append({"q": q, "x": x, "y": y, "z": z})
        bloch_data = json.dumps(bvecs)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{html_mod.escape(title)}</title>
<style>
  :root {{
    --bg: #0f0f1a;
    --panel: #1a1a2e;
    --border: #2d2d50;
    --accent: #6c63ff;
    --accent2: #ff6584;
    --text: #e0e0ff;
    --subtext: #8888aa;
    --wire: #4444aa;
    --gate-fill: #2d2d5e;
    --gate-stroke: #6c63ff;
    --font: 'Courier New', monospace;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    background: var(--bg);
    color: var(--text);
    font-family: var(--font);
    padding: 20px;
    min-height: 100vh;
  }}
  h1 {{ color: var(--accent); font-size: 1.5rem; margin-bottom: 4px; }}
  h2 {{ color: var(--accent2); font-size: 1rem; margin: 16px 0 8px; text-transform: uppercase;
        letter-spacing: 2px; }}
  .subtitle {{ color: var(--subtext); font-size: 0.8rem; margin-bottom: 20px; }}
  .panel {{
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 16px;
    margin-bottom: 16px;
    overflow-x: auto;
  }}
  .ascii-circuit {{
    font-family: var(--font);
    font-size: 13px;
    line-height: 1.6;
    color: #aaaacc;
    white-space: pre;
  }}
  #circuit-svg {{ width: 100%; overflow-x: auto; }}
  .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
  @media (max-width: 700px) {{ .grid {{ grid-template-columns: 1fr; }} }}
  .bar-container {{
    display: flex;
    flex-direction: column;
    gap: 3px;
    max-height: 400px;
    overflow-y: auto;
  }}
  .bar-row {{ display: flex; align-items: center; gap: 8px; font-size: 11px; }}
  .bar-label {{ width: 80px; text-align: right; color: var(--subtext); flex-shrink: 0; }}
  .bar-track {{ flex: 1; height: 16px; background: #1a1a2e; border-radius: 3px; position: relative; }}
  .bar-fill {{
    height: 100%;
    border-radius: 3px;
    position: absolute;
    left: 0; top: 0;
    transition: width 0.3s;
  }}
  .bar-val {{ width: 60px; text-align: left; color: var(--text); flex-shrink: 0; }}
  .bloch-grid {{
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
  }}
  .bloch-wrap {{
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 4px;
  }}
  .bloch-label {{ font-size: 11px; color: var(--subtext); }}
  svg.bloch {{
    width: 120px;
    height: 120px;
    background: #12122a;
    border-radius: 50%;
    border: 1px solid var(--border);
  }}
  #step-controls {{
    display: flex;
    gap: 8px;
    align-items: center;
    flex-wrap: wrap;
    margin-bottom: 12px;
  }}
  button {{
    background: var(--gate-fill);
    color: var(--text);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 6px 14px;
    cursor: pointer;
    font-family: var(--font);
    font-size: 13px;
    transition: background 0.2s;
  }}
  button:hover {{ background: var(--accent); color: #fff; }}
  button:disabled {{ opacity: 0.4; cursor: not-allowed; }}
  #step-info {{ color: var(--subtext); font-size: 12px; }}
  .norm-bar {{ height: 4px; background: linear-gradient(90deg, var(--accent), var(--accent2));
               border-radius: 2px; margin: 8px 0; }}
  .entropy-label {{ font-size: 11px; color: var(--subtext); }}
  #state-norm {{ font-size: 12px; color: var(--subtext); margin-top: 8px; }}
</style>
</head>
<body>
<h1>⚛ QSim — Quantum Circuit Visualizer</h1>
<p class="subtitle">{html_mod.escape(circuit.name)} &nbsp;|&nbsp;
  {circuit.n} qubits &nbsp;|&nbsp; {len(circuit)} gates &nbsp;|&nbsp; depth {circuit.depth()}</p>

<div class="panel">
  <h2>Circuit Diagram (ASCII)</h2>
  <div class="ascii-circuit" id="ascii-art"></div>
</div>

<div class="panel">
  <h2>Circuit Diagram (SVG)</h2>
  <div id="circuit-svg"></div>
</div>

{'<div class="panel"><h2>Amplitude Spectrum</h2><div class="bar-container" id="amp-bars"></div><p id="state-norm"></p></div>' if state_data else ''}

{'<div class="panel"><h2>Bloch Spheres (single-qubit reduced states)</h2><div class="bloch-grid" id="bloch-grid"></div></div>' if bloch_data else ''}

{'<div class="panel"><h2>Measurement Histogram (' + str(shots) + ' shots)</h2><div class="bar-container" id="shot-bars"></div></div>' if counts_data != 'null' else ''}

<div class="panel">
  <h2>Step-Through</h2>
  <div id="step-controls">
    <button id="btn-prev" disabled>← Prev</button>
    <button id="btn-next">Next →</button>
    <button id="btn-reset">Reset</button>
    <span id="step-info">Step 0 / {len(circuit)}</span>
  </div>
  <div class="bar-container" id="step-bars"></div>
  <div class="ascii-circuit" id="step-ascii"></div>
</div>

<script>
(function() {{
  const ASCII = {json.dumps(ascii_art)};
  const GATES = {json.dumps(gate_data)};
  const STATE = {json.dumps(state_data)};
  const COUNTS = {counts_data};
  const BLOCH = {bloch_data if bloch_data else 'null'};
  const N_QUBITS = {circuit.n};
  const SHOTS = {shots};

  // Render ASCII
  document.getElementById('ascii-art').textContent = ASCII;

  // Render SVG circuit
  renderCircuitSVG();

  // Render amplitude bars
  if (STATE) {{
    renderAmpBars('amp-bars', STATE.probs, STATE.phases, STATE.labels);
    const norm = STATE.probs.reduce((a, b) => a + b, 0);
    document.getElementById('state-norm').textContent =
      `Norm: ${{norm.toFixed(8)}} | Non-zero terms: ${{STATE.probs.filter(p => p > 1e-10).length}} / ${{STATE.probs.length}}`;
  }}

  // Render Bloch spheres
  if (BLOCH) {{
    const grid = document.getElementById('bloch-grid');
    BLOCH.forEach(bv => {{
      const wrap = document.createElement('div');
      wrap.className = 'bloch-wrap';
      const svg = makeBlochSVG(bv.x, bv.y, bv.z);
      const lbl = document.createElement('div');
      lbl.className = 'bloch-label';
      lbl.textContent = 'q' + bv.q + ' (x=' + bv.x.toFixed(2) + ', y=' + bv.y.toFixed(2) + ', z=' + bv.z.toFixed(2) + ')';
      wrap.appendChild(svg);
      wrap.appendChild(lbl);
      grid.appendChild(wrap);
    }});
  }}

  // Render shot histogram
  if (COUNTS) {{
    const vals = Object.values(COUNTS);
    const maxVal = Math.max(...vals);
    const bars = document.getElementById('shot-bars');
    Object.entries(COUNTS)
      .sort((a, b) => b[1] - a[1])
      .forEach(([bits, count]) => {{
        const prob = count / SHOTS;
        const color = hslColor(parseInt(bits, 2) / Math.pow(2, N_QUBITS), 0.8, 0.6);
        bars.appendChild(makeBar(`|${{bits}}⟩`, count / maxVal, color,
          `${{count}} (${{(prob*100).toFixed(1)}}%)`));
      }});
  }}

  // Step-through
  let currentStep = 0;
  const totalSteps = GATES.length;
  const stateHistory = [initialState()];
  computeAllSteps();

  function computeAllSteps() {{
    let s = initialState();
    stateHistory[0] = s;
    for (let i = 0; i < GATES.length; i++) {{
      s = applyGate(s, GATES[i]);
      stateHistory[i + 1] = s;
    }}
    renderStep(0);
  }}

  document.getElementById('btn-next').addEventListener('click', () => {{
    if (currentStep < totalSteps) {{
      currentStep++;
      renderStep(currentStep);
    }}
  }});
  document.getElementById('btn-prev').addEventListener('click', () => {{
    if (currentStep > 0) {{
      currentStep--;
      renderStep(currentStep);
    }}
  }});
  document.getElementById('btn-reset').addEventListener('click', () => {{
    currentStep = 0;
    renderStep(0);
  }});

  function renderStep(step) {{
    document.getElementById('btn-prev').disabled = step === 0;
    document.getElementById('btn-next').disabled = step === totalSteps;
    document.getElementById('step-info').textContent =
      `Step ${{step}} / ${{totalSteps}}` +
      (step > 0 ? ` — after ${{GATES[step-1].name}} on q[${{GATES[step-1].qubits.join(',')}}]` : '');

    const s = stateHistory[step];
    const bars = document.getElementById('step-bars');
    bars.innerHTML = '';
    const maxP = Math.max(...s.probs);
    s.probs.forEach((p, i) => {{
      if (p < 1e-10) return;
      const bits = i.toString(2).padStart(N_QUBITS, '0');
      const phase = s.phases[i];
      const color = phaseToColor(phase);
      bars.appendChild(makeBar(`|${{bits}}⟩`, maxP > 0 ? p / maxP : 0, color,
        `${{p.toFixed(4)}} ∠${{(phase*180/Math.PI).toFixed(0)}}°`));
    }});
  }}

  // --- SVG Circuit ---
  function renderCircuitSVG() {{
    const qubitH = 50;
    const colW = 70;
    const margin = 60;
    const svgH = N_QUBITS * qubitH + 40;
    const numCols = Math.max(GATES.length, 1);
    const svgW = margin + numCols * colW + margin;

    let svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${{svgW}} ${{svgH}}"
      style="background:#12122a; border-radius:8px; font-family:monospace; font-size:12px;">`;

    // Qubit labels
    for (let q = 0; q < N_QUBITS; q++) {{
      const y = 20 + q * qubitH;
      svg += `<text x="10" y="${{y+5}}" fill="#8888aa" font-size="12">q${{q}}</text>`;
      svg += `<line x1="${{margin}}" y1="${{y}}" x2="${{svgW - margin/2}}" y2="${{y}}"
        stroke="#2d2d5e" stroke-width="2"/>`;
    }}

    // Gates
    GATES.forEach((g, idx) => {{
      const x = margin + idx * colW + colW/2;
      if (g.qubits.length === 1) {{
        const y = 20 + g.qubits[0] * qubitH;
        const lbl = g.name.length > 4 ? g.name.slice(0, 4) : g.name;
        svg += `<rect x="${{x-18}}" y="${{y-14}}" width="36" height="28"
          rx="4" fill="#2d2d5e" stroke="#6c63ff" stroke-width="1.5"/>`;
        svg += `<text x="${{x}}" y="${{y+5}}" fill="#e0e0ff" text-anchor="middle"
          font-size="11">${{escSVG(lbl)}}</text>`;
      }} else if (g.qubits.length === 2) {{
        const [q0, q1] = g.qubits;
        const y0 = 20 + q0 * qubitH;
        const y1 = 20 + q1 * qubitH;
        const yMin = Math.min(y0, y1);
        const yMax = Math.max(y0, y1);
        // Vertical connector
        svg += `<line x1="${{x}}" y1="${{yMin}}" x2="${{x}}" y2="${{yMax}}"
          stroke="#6c63ff" stroke-width="1.5"/>`;
        if (g.name === 'CNOT' || g.name === 'CX') {{
          svg += `<circle cx="${{x}}" cy="${{y0}}" r="6" fill="#6c63ff"/>`;
          svg += `<circle cx="${{x}}" cy="${{y1}}" r="12" fill="none" stroke="#6c63ff" stroke-width="1.5"/>`;
          svg += `<line x1="${{x-12}}" y1="${{y1}}" x2="${{x+12}}" y2="${{y1}}" stroke="#6c63ff" stroke-width="1.5"/>`;
          svg += `<line x1="${{x}}" y1="${{y1-12}}" x2="${{x}}" y2="${{y1+12}}" stroke="#6c63ff" stroke-width="1.5"/>`;
        }} else if (g.name === 'SWAP') {{
          ['y0', 'y1'].forEach((yy, i) => {{
            const yyy = i === 0 ? y0 : y1;
            const d = 8;
            svg += `<line x1="${{x-d}}" y1="${{yyy-d}}" x2="${{x+d}}" y2="${{yyy+d}}" stroke="#ff6584" stroke-width="2"/>`;
            svg += `<line x1="${{x+d}}" y1="${{yyy-d}}" x2="${{x-d}}" y2="${{yyy+d}}" stroke="#ff6584" stroke-width="2"/>`;
          }});
        }} else {{
          const lbl = g.name.startsWith('C-') || g.name.startsWith('C1-')
            ? g.name.slice(g.name.lastIndexOf('-')+1, g.name.lastIndexOf('-')+5)
            : g.name.slice(0, 4);
          svg += `<circle cx="${{x}}" cy="${{y0}}" r="6" fill="#6c63ff"/>`;
          svg += `<rect x="${{x-18}}" y="${{y1-14}}" width="36" height="28"
            rx="4" fill="#2d2d5e" stroke="#6c63ff" stroke-width="1.5"/>`;
          svg += `<text x="${{x}}" y="${{y1+5}}" fill="#e0e0ff" text-anchor="middle"
            font-size="11">${{escSVG(lbl)}}</text>`;
        }}
      }} else if (g.qubits.length >= 3) {{
        const qs = g.qubits;
        const yMin = 20 + Math.min(...qs) * qubitH;
        const yMax = 20 + Math.max(...qs) * qubitH;
        svg += `<line x1="${{x}}" y1="${{yMin}}" x2="${{x}}" y2="${{yMax}}"
          stroke="#6c63ff" stroke-width="1.5"/>`;
        qs.slice(0,-1).forEach(q => {{
          svg += `<circle cx="${{x}}" cy="${{20 + q*qubitH}}" r="6" fill="#6c63ff"/>`;
        }});
        const qLast = qs[qs.length-1];
        const yL = 20 + qLast * qubitH;
        svg += `<circle cx="${{x}}" cy="${{yL}}" r="12" fill="none" stroke="#6c63ff" stroke-width="1.5"/>`;
        svg += `<line x1="${{x-12}}" y1="${{yL}}" x2="${{x+12}}" y2="${{yL}}" stroke="#6c63ff" stroke-width="1.5"/>`;
        svg += `<line x1="${{x}}" y1="${{yL-12}}" x2="${{x}}" y2="${{yL+12}}" stroke="#6c63ff" stroke-width="1.5"/>`;
      }}
    }});

    svg += '</svg>';
    document.getElementById('circuit-svg').innerHTML = svg;
  }}

  // --- Quantum state simulation in JS ---
  function initialState() {{
    const dim = 1 << N_QUBITS;
    const re = new Array(dim).fill(0);
    const im = new Array(dim).fill(0);
    re[0] = 1;
    const probs = re.map((r, i) => r*r + im[i]*im[i]);
    const phases = re.map((r, i) => Math.atan2(im[i], r));
    return {{ re, im, probs, phases }};
  }}

  function applyGate(state, g) {{
    const n = N_QUBITS;
    const dim = 1 << n;
    let re = state.re.slice();
    let im = state.im.slice();
    const m = g.matrix;  // [re0, im0, re1, im1, ...] flattened
    const k = g.qubits.length;
    const d = 1 << k;
    const bits = g.qubits.map(q => n - 1 - q);
    const masks = bits.map(b => 1 << b);

    for (let i = 0; i < dim; i++) {{
      if (masks.some(mk => i & mk)) continue;
      // Collect indices
      const idxs = [];
      for (let combo = 0; combo < d; combo++) {{
        let idx = i;
        for (let bp = 0; bp < k; bp++) {{
          if ((combo >> (k-1-bp)) & 1) idx |= masks[bp];
        }}
        idxs.push(idx);
      }}
      const oldRe = idxs.map(ix => re[ix]);
      const oldIm = idxs.map(ix => im[ix]);
      for (let row = 0; row < d; row++) {{
        let newRe = 0, newIm = 0;
        for (let col = 0; col < d; col++) {{
          const mr = m[row*d+col][0], mi = m[row*d+col][1];
          newRe += mr*oldRe[col] - mi*oldIm[col];
          newIm += mr*oldIm[col] + mi*oldRe[col];
        }}
        re[idxs[row]] = newRe;
        im[idxs[row]] = newIm;
      }}
    }}

    const probs = re.map((r, i) => r*r + im[i]*im[i]);
    const phases = re.map((r, i) => Math.atan2(im[i], r));
    return {{ re, im, probs, phases }};
  }}

  // --- Bar chart helpers ---
  function renderAmpBars(containerId, probs, phases, labels) {{
    const c = document.getElementById(containerId);
    const maxP = Math.max(...probs);
    probs.forEach((p, i) => {{
      if (p < 1e-10) return;
      const color = phaseToColor(phases[i]);
      c.appendChild(makeBar(labels[i], maxP > 0 ? p / maxP : 0, color,
        `${{p.toFixed(4)}} ∠${{(phases[i]*180/Math.PI).toFixed(0)}}°`));
    }});
  }}

  function makeBar(label, fraction, color, valText) {{
    const row = document.createElement('div');
    row.className = 'bar-row';
    row.innerHTML = `<span class="bar-label">${{label}}</span>
      <div class="bar-track">
        <div class="bar-fill" style="width:${{(fraction*100).toFixed(1)}}%;background:${{color}}"></div>
      </div>
      <span class="bar-val">${{valText}}</span>`;
    return row;
  }}

  function phaseToColor(phase) {{
    // Map phase [-π, π] to hue [0, 360]
    const hue = ((phase + Math.PI) / (2 * Math.PI) * 360) | 0;
    return `hsl(${{hue}}, 80%, 55%)`;
  }}

  function hslColor(frac, s, l) {{
    return `hsl(${{(frac * 360) | 0}}, ${{(s*100)|0}}%, ${{(l*100)|0}}%)`;
  }}

  // --- Bloch sphere SVG ---
  function makeBlochSVG(bx, by, bz) {{
    const r = 50;
    const cx = 60, cy = 60;
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('class', 'bloch');
    svg.setAttribute('viewBox', '0 0 120 120');

    const ns = 'http://www.w3.org/2000/svg';
    // Outer sphere
    const circle = document.createElementNS(ns, 'circle');
    circle.setAttribute('cx', cx); circle.setAttribute('cy', cy);
    circle.setAttribute('r', r);
    circle.setAttribute('fill', 'none');
    circle.setAttribute('stroke', '#2d2d5e');
    circle.setAttribute('stroke-width', '1.5');
    svg.appendChild(circle);

    // Equator ellipse
    const el = document.createElementNS(ns, 'ellipse');
    el.setAttribute('cx', cx); el.setAttribute('cy', cy);
    el.setAttribute('rx', r); el.setAttribute('ry', r*0.25);
    el.setAttribute('fill', 'none');
    el.setAttribute('stroke', '#2d2d5e');
    el.setAttribute('stroke-dasharray', '3,3');
    svg.appendChild(el);

    // Axes
    [['#5555aa', cx, cy-r, cx, cy+r],   // Z
     ['#5555aa', cx-r, cy, cx+r, cy],   // X
    ].forEach(([color, x1,y1,x2,y2]) => {{
      const l = document.createElementNS(ns, 'line');
      l.setAttribute('x1',x1); l.setAttribute('y1',y1);
      l.setAttribute('x2',x2); l.setAttribute('y2',y2);
      l.setAttribute('stroke', color); l.setAttribute('stroke-width', '0.5');
      svg.appendChild(l);
    }});

    // Axis labels
    const lbls = [['|0⟩', cx+3, cy-r-4], ['|1⟩', cx+3, cy+r+12],
                  ['X', cx+r+4, cy+4], ['Y', cx+5, cy+5]];
    lbls.forEach(([txt, x, y]) => {{
      const t = document.createElementNS(ns, 'text');
      t.setAttribute('x', x); t.setAttribute('y', y);
      t.setAttribute('fill', '#666688'); t.setAttribute('font-size', '9');
      t.textContent = txt;
      svg.appendChild(t);
    }});

    // Bloch vector: project (bx, by, bz) to 2D
    // x_screen = cx + r*bx, y_screen = cy - r*(bz + 0.3*by) (approximate)
    const sx = cx + r * bx;
    const sy = cy - r * (bz + 0.3 * by);

    const line = document.createElementNS(ns, 'line');
    line.setAttribute('x1', cx); line.setAttribute('y1', cy);
    line.setAttribute('x2', sx); line.setAttribute('y2', sy);
    line.setAttribute('stroke', '#6c63ff'); line.setAttribute('stroke-width', '2');
    svg.appendChild(line);

    const dot = document.createElementNS(ns, 'circle');
    dot.setAttribute('cx', sx); dot.setAttribute('cy', sy);
    dot.setAttribute('r', 4);
    dot.setAttribute('fill', '#ff6584');
    svg.appendChild(dot);

    return svg;
  }}

  function escSVG(s) {{
    return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }}

}})();
</script>
</body>
</html>"""

    return html


def _circuit_to_json(circuit: Circuit) -> list:
    """Convert circuit instructions to a JSON-serialisable list for the JS simulator."""
    result = []
    for instr in circuit._instructions:
        if instr.kind != "gate":
            continue
        # Matrix as list of [re, im] pairs
        mat = [[v.real, v.imag] for v in instr.gate.matrix]
        result.append({
            "name": instr.gate.name,
            "qubits": instr.qubits,
            "matrix": mat,
        })
    return result


def _state_to_json(state: QuantumState) -> dict:
    """Serialize state vector for the HTML visualizer."""
    probs = state.probabilities()
    phases = [cmath.phase(a) for a in state._amp]
    labels = [f"|{format(i, f'0{state.n}b')}⟩" for i in range(state.dim)]
    return {
        "probs": probs,
        "phases": phases,
        "labels": labels,
        "n": state.n,
    }
