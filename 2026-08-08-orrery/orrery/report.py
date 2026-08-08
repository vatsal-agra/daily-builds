"""Self-contained HTML reports: an interactive trajectory playback
viewer, and a Barnes-Hut speed/accuracy benchmark report. Both are
single files with everything (data, CSS, JS) inlined -- open directly
in a browser, no server needed.
"""

import json
import time
import random
import html as html_escape

from .vector import Vec3
from .body import Body
from . import bruteforce
from . import octree


# ----------------------------------------------------------------------
# Trajectory viewer
# ----------------------------------------------------------------------

def history_to_traj_data(history, title, description):
    if not history:
        raise ValueError("history_to_traj_data: history is empty")

    names = [b["name"] for b in history[0]["bodies"]]
    colors = [b["color"] for b in history[0]["bodies"]]
    frames = []
    for snap in history:
        frame_bodies = [
            [round(b["position"][0], 6), round(b["position"][1], 6), round(b["position"][2], 6),
             1 if b["alive"] else 0, b["mass"], round(b["radius"], 6),
             round(b["velocity"][0], 6), round(b["velocity"][1], 6), round(b["velocity"][2], 6)]
            for b in snap["bodies"]
        ]
        frames.append({
            "t": snap["t"],
            "bodies": frame_bodies,
            "energy": snap["energy"],
            "momentum": snap["momentum"],
            "angular_momentum": snap["angular_momentum"],
        })

    e0 = frames[0]["energy"]
    return {
        "title": title,
        "description": description,
        "names": names,
        "colors": colors,
        "frames": frames,
        "e0": e0,
    }


def write_trajectory_report(history, title, description, out_path):
    data = history_to_traj_data(history, title, description)
    html_doc = _TRAJ_TEMPLATE.replace("__TITLE__", html_escape.escape(title))
    html_doc = html_doc.replace("__DATA_JSON__", json.dumps(data))
    with open(out_path, "w") as f:
        f.write(html_doc)
    return out_path


_TRAJ_TEMPLATE = r"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Orrery — __TITLE__</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: #0b0e14; color: #d8dee9;
    font-family: -apple-system, "Segoe UI", Roboto, sans-serif;
    display: flex; flex-direction: column; height: 100vh; overflow: hidden;
  }
  header {
    padding: 10px 16px; border-bottom: 1px solid #1c2230; display: flex;
    align-items: baseline; gap: 12px; flex-shrink: 0;
  }
  header h1 { font-size: 15px; margin: 0; font-weight: 600; color: #e8ecf4; }
  header p { margin: 0; font-size: 12px; color: #7d8aa3; }
  #main { flex: 1; display: flex; min-height: 0; }
  #canvas-wrap { flex: 1; position: relative; }
  canvas { display: block; width: 100%; height: 100%; background: #05070c; cursor: grab; }
  canvas:active { cursor: grabbing; }
  #sidebar {
    width: 260px; border-left: 1px solid #1c2230; padding: 12px;
    overflow-y: auto; flex-shrink: 0; font-size: 12px;
  }
  #sidebar h2 { font-size: 12px; text-transform: uppercase; letter-spacing: .05em;
    color: #7d8aa3; margin: 14px 0 6px; }
  #sidebar h2:first-child { margin-top: 0; }
  .stat { display: flex; justify-content: space-between; padding: 2px 0; }
  .stat span:last-child { color: #e8ecf4; font-variant-numeric: tabular-nums; }
  #energy-chart { width: 100%; height: 60px; background: #0e1320; border-radius: 4px; }
  #bodylist { display: flex; flex-direction: column; gap: 2px; }
  .body-row {
    display: flex; align-items: center; gap: 6px; padding: 3px 4px; border-radius: 4px;
    cursor: pointer;
  }
  .body-row:hover { background: #151b28; }
  .body-row.selected { background: #1c2942; }
  .swatch { width: 9px; height: 9px; border-radius: 50%; flex-shrink: 0; }
  .body-row .name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .body-row.dead { opacity: 0.35; text-decoration: line-through; }
  #controls {
    border-top: 1px solid #1c2230; padding: 10px 16px; display: flex; align-items: center;
    gap: 10px; flex-shrink: 0; font-size: 12px;
  }
  button {
    background: #1c2230; color: #d8dee9; border: 1px solid #2a3245; border-radius: 5px;
    padding: 5px 10px; cursor: pointer; font-size: 12px;
  }
  button:hover { background: #262e42; }
  input[type=range] { flex-shrink: 0; }
  #timeline { flex: 1; }
  #time-label { width: 90px; text-align: right; font-variant-numeric: tabular-nums; color: #9aa7c2; }
  #speed-label { width: 46px; text-align: right; color: #9aa7c2; }
  #info-panel { border-top: 1px solid #1c2230; margin-top: 8px; padding-top: 8px; }
  #info-panel .stat span:last-child { color: #ffd24a; }
  #hint { position: absolute; bottom: 8px; left: 8px; font-size: 11px; color: #4b5670; pointer-events: none; }
</style>
</head>
<body>
<header>
  <h1>Orrery — __TITLE__</h1>
  <p id="desc"></p>
</header>
<div id="main">
  <div id="canvas-wrap">
    <canvas id="canvas"></canvas>
    <div id="hint">scroll = zoom · drag = pan · click a body to inspect</div>
  </div>
  <div id="sidebar">
    <h2>Simulation</h2>
    <div class="stat"><span>Bodies</span><span id="stat-n"></span></div>
    <div class="stat"><span>Time</span><span id="stat-t"></span></div>
    <div class="stat"><span>Energy drift</span><span id="stat-edrift"></span></div>
    <svg id="energy-chart"></svg>
    <h2>Bodies</h2>
    <div id="bodylist"></div>
    <div id="info-panel" style="display:none">
      <h2>Selected</h2>
      <div class="stat"><span>Name</span><span id="info-name"></span></div>
      <div class="stat"><span>Mass</span><span id="info-mass"></span></div>
      <div class="stat"><span>|v|</span><span id="info-speed"></span></div>
      <div class="stat"><span>Position</span><span id="info-pos"></span></div>
    </div>
  </div>
</div>
<div id="controls">
  <button id="play">▶ Play</button>
  <button id="reset-view">Fit all</button>
  <button id="fit-inner">Fit inner (median)</button>
  <span id="time-label">t = 0</span>
  <input id="timeline" type="range" min="0" max="0" value="0" step="1">
  <span>speed</span>
  <input id="speed" type="range" min="1" max="60" value="10" step="1">
  <span id="speed-label">10 f/s</span>
</div>
<script>
const DATA = __DATA_JSON__;
document.getElementById('desc').textContent = DATA.description;

const canvas = document.getElementById('canvas');
const ctx = canvas.getContext('2d');
const wrap = document.getElementById('canvas-wrap');
function resize() {
  canvas.width = wrap.clientWidth * devicePixelRatio;
  canvas.height = wrap.clientHeight * devicePixelRatio;
}
window.addEventListener('resize', resize);
resize();

// Fixed isometric-ish projection: rotate about X then project X,Y.
const ELEV = 0.45; // radians
function project(x, y, z) {
  const y2 = y * Math.cos(ELEV) - z * Math.sin(ELEV);
  const depth = y * Math.sin(ELEV) + z * Math.cos(ELEV);
  return [x, y2, depth];
}

let scale = null, offsetX = 0, offsetY = 0;
function autoFit() {
  let maxR = 1e-6;
  for (const f of DATA.frames) {
    for (const b of f.bodies) {
      const [px, py] = project(b[0], b[1], b[2]);
      maxR = Math.max(maxR, Math.abs(px), Math.abs(py));
    }
  }
  scale = (Math.min(canvas.width, canvas.height) * 0.42) / maxR;
  offsetX = canvas.width / 2;
  offsetY = canvas.height / 2;
}
autoFit();

// "Fit all" scales to the single farthest-ever body, which -- in a scene
// with a big range of orbit sizes (e.g. Mercury at 0.4 AU vs Neptune at
// 30 AU) -- squashes everything interesting into a tiny cluster of
// overlapping dots at the center. This scales to a few times the
// *median* distance instead, trading "everything visible" for "the
// typical body visible", with pan/zoom available for the rest.
function fitInner() {
  const frame = DATA.frames[frameIdx];
  const dists = frame.bodies.filter(b => b[3]).map(b => {
    const [px, py] = project(b[0], b[1], b[2]);
    return Math.hypot(px, py);
  }).sort((a, b) => a - b);
  if (!dists.length) return;
  const median = dists[Math.floor(dists.length / 2)] || 1e-6;
  scale = (Math.min(canvas.width, canvas.height) * 0.42) / Math.max(median * 3, 1e-6);
  offsetX = canvas.width / 2;
  offsetY = canvas.height / 2;
}

let frameIdx = 0;
let playing = false;
let selected = null;
const trailLen = 250;

const bodylistEl = document.getElementById('bodylist');
DATA.names.forEach((name, i) => {
  const row = document.createElement('div');
  row.className = 'body-row';
  row.dataset.idx = i;
  row.innerHTML = `<span class="swatch" style="background:${DATA.colors[i]}"></span><span class="name">${name}</span>`;
  row.addEventListener('click', () => { selected = (selected === i) ? null : i; renderSidebarSelection(); });
  bodylistEl.appendChild(row);
});

function renderSidebarSelection() {
  document.querySelectorAll('.body-row').forEach(r => r.classList.toggle('selected', Number(r.dataset.idx) === selected));
  const panel = document.getElementById('info-panel');
  if (selected === null) { panel.style.display = 'none'; return; }
  panel.style.display = 'block';
  const frame = DATA.frames[frameIdx];
  const b = frame.bodies[selected];
  document.getElementById('info-name').textContent = DATA.names[selected] + (b[3] ? '' : ' (merged away)');
  document.getElementById('info-mass').textContent = b[4].toExponential(3);
  const speed = b[3] ? Math.hypot(b[6], b[7], b[8]) : 0;
  document.getElementById('info-speed').textContent = b[3] ? speed.toFixed(4) : '—';
  document.getElementById('info-pos').textContent = `(${b[0].toFixed(3)}, ${b[1].toFixed(3)}, ${b[2].toFixed(3)})`;
}

const timeline = document.getElementById('timeline');
timeline.max = DATA.frames.length - 1;
const timeLabel = document.getElementById('time-label');
const playBtn = document.getElementById('play');
const speedSlider = document.getElementById('speed');
const speedLabel = document.getElementById('speed-label');

function draw() {
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  const frame = DATA.frames[frameIdx];

  // trails
  const startTrail = Math.max(0, frameIdx - trailLen);
  for (let i = 0; i < DATA.names.length; i++) {
    ctx.beginPath();
    let started = false;
    for (let f = startTrail; f <= frameIdx; f++) {
      const b = DATA.frames[f].bodies[i];
      if (!b[3]) { started = false; continue; }
      const [px, py] = project(b[0], b[1], b[2]);
      const sx = offsetX + px * scale, sy = offsetY - py * scale;
      if (!started) { ctx.moveTo(sx, sy); started = true; } else { ctx.lineTo(sx, sy); }
    }
    ctx.strokeStyle = DATA.colors[i] + '55';
    ctx.lineWidth = 1;
    ctx.stroke();
  }

  // bodies. Marker radius is log(mass)-scaled relative to the other
  // *currently alive* bodies in this frame, independent of camera zoom --
  // physical radii (b[5]) are usually orders of magnitude too small to
  // see at solar-system scale, and a fixed pixel size can't tell a star
  // from a planet, so screen size instead encodes relative mass.
  const aliveMasses = frame.bodies.filter(b => b[3]).map(b => Math.log10(Math.max(b[4], 1e-300)));
  const minLogM = Math.min(...aliveMasses), maxLogM = Math.max(...aliveMasses);
  const logSpan = maxLogM - minLogM;
  for (let i = 0; i < DATA.names.length; i++) {
    const b = frame.bodies[i];
    if (!b[3]) continue;
    const [px, py, depth] = project(b[0], b[1], b[2]);
    const sx = offsetX + px * scale, sy = offsetY - py * scale;
    const logM = Math.log10(Math.max(b[4], 1e-300));
    const t = logSpan > 1e-9 ? (logM - minLogM) / logSpan : 0.5;
    const r = 2.5 + t * 12.5;
    ctx.beginPath();
    ctx.arc(sx, sy, r, 0, Math.PI * 2);
    ctx.fillStyle = DATA.colors[i];
    ctx.fill();
    if (i === selected) {
      ctx.strokeStyle = '#ffffff';
      ctx.lineWidth = 1.5;
      ctx.stroke();
    }
  }

  document.getElementById('stat-n').textContent = frame.bodies.filter(b => b[3]).length + ' / ' + DATA.names.length;
  document.getElementById('stat-t').textContent = frame.t.toFixed(4);
  const drift = DATA.e0 !== 0 ? Math.abs((frame.energy - DATA.e0) / DATA.e0) : Math.abs(frame.energy - DATA.e0);
  document.getElementById('stat-edrift').textContent = drift.toExponential(2);
  timeLabel.textContent = 't = ' + frame.t.toFixed(3);
  timeline.value = frameIdx;
  renderSidebarSelection();
  drawEnergyChart();
}

function drawEnergyChart() {
  const svg = document.getElementById('energy-chart');
  const w = svg.clientWidth || 240, h = 60;
  const energies = DATA.frames.map(f => f.energy);
  const emin = Math.min(...energies), emax = Math.max(...energies);
  const span = (emax - emin) || 1;
  let d = '';
  DATA.frames.forEach((f, i) => {
    const x = (i / (DATA.frames.length - 1 || 1)) * w;
    const y = h - ((f.energy - emin) / span) * (h - 6) - 3;
    d += (i === 0 ? 'M' : 'L') + x.toFixed(1) + ',' + y.toFixed(1) + ' ';
  });
  const cx = (frameIdx / (DATA.frames.length - 1 || 1)) * w;
  svg.innerHTML = `<path d="${d}" fill="none" stroke="#5ea0ff" stroke-width="1.3"/>
    <line x1="${cx}" y1="0" x2="${cx}" y2="${h}" stroke="#ffd24a" stroke-width="1"/>`;
}

let lastTick = null;
function tick(ts) {
  if (playing) {
    const fps = Number(speedSlider.value);
    if (lastTick === null) lastTick = ts;
    const elapsed = ts - lastTick;
    if (elapsed > 1000 / fps) {
      frameIdx = (frameIdx + 1) % DATA.frames.length;
      lastTick = ts;
      draw();
    }
  }
  requestAnimationFrame(tick);
}
requestAnimationFrame(tick);

playBtn.addEventListener('click', () => {
  playing = !playing;
  playBtn.textContent = playing ? '⏸ Pause' : '▶ Play';
  lastTick = null;
});
timeline.addEventListener('input', () => { frameIdx = Number(timeline.value); draw(); });
speedSlider.addEventListener('input', () => { speedLabel.textContent = speedSlider.value + ' f/s'; });
document.getElementById('reset-view').addEventListener('click', () => { autoFit(); draw(); });
document.getElementById('fit-inner').addEventListener('click', () => { fitInner(); draw(); });

// pan & zoom
let dragging = false, lastX = 0, lastY = 0;
canvas.addEventListener('mousedown', e => { dragging = true; lastX = e.clientX; lastY = e.clientY; });
window.addEventListener('mouseup', () => dragging = false);
window.addEventListener('mousemove', e => {
  if (!dragging) return;
  offsetX += (e.clientX - lastX) * devicePixelRatio;
  offsetY += (e.clientY - lastY) * devicePixelRatio;
  lastX = e.clientX; lastY = e.clientY;
  draw();
});
canvas.addEventListener('wheel', e => {
  e.preventDefault();
  const factor = e.deltaY < 0 ? 1.1 : 0.9;
  scale *= factor;
  draw();
}, { passive: false });
canvas.addEventListener('click', e => {
  const rect = canvas.getBoundingClientRect();
  const mx = (e.clientX - rect.left) * devicePixelRatio;
  const my = (e.clientY - rect.top) * devicePixelRatio;
  const frame = DATA.frames[frameIdx];
  let best = null, bestDist = 22 * devicePixelRatio;
  for (let i = 0; i < DATA.names.length; i++) {
    const b = frame.bodies[i];
    if (!b[3]) continue;
    const [px, py] = project(b[0], b[1], b[2]);
    const sx = offsetX + px * scale, sy = offsetY - py * scale;
    const d = Math.hypot(sx - mx, sy - my);
    if (d < bestDist) { bestDist = d; best = i; }
  }
  if (best !== null) { selected = best; renderSidebarSelection(); }
});

draw();
</script>
</body>
</html>
"""


# ----------------------------------------------------------------------
# Barnes-Hut benchmark report
# ----------------------------------------------------------------------

def run_benchmark(ns=(10, 30, 100, 300), thetas=(0.0, 0.3, 0.5, 0.8, 1.2), seed=99):
    """For each N, build a random cloud and measure brute-force vs.
    Barnes-Hut wall-clock time, and for each theta measure Barnes-Hut's
    max relative force error against brute force. Returns a results dict
    consumed by render_benchmark_html.
    """
    rng = random.Random(seed)
    timing_rows = []
    accuracy_rows = []

    for n in ns:
        bodies = [
            Body(f"b{i}", rng.uniform(0.5, 2.0),
                 Vec3(rng.uniform(-5, 5), rng.uniform(-5, 5), rng.uniform(-5, 5)),
                 Vec3(0, 0, 0))
            for i in range(n)
        ]

        t0 = time.perf_counter()
        a_bf = bruteforce.compute_accelerations(bodies, G=1.0, softening=0.02)
        t_bf = time.perf_counter() - t0

        t0 = time.perf_counter()
        a_bh = octree.compute_accelerations(bodies, G=1.0, theta=0.5, softening=0.02)
        t_bh = time.perf_counter() - t0

        timing_rows.append({"n": n, "bruteforce_s": t_bf, "barnes_hut_s": t_bh})

        if n == ns[-1] or n == ns[len(ns) // 2]:
            for theta in thetas:
                a_theta = octree.compute_accelerations(bodies, G=1.0, theta=theta, softening=0.02)
                errs = []
                for af, at in zip(a_bf, a_theta):
                    denom = max(af.norm(), 1e-12)
                    errs.append((af - at).norm() / denom)
                accuracy_rows.append({"n": n, "theta": theta, "max_rel_err": max(errs), "mean_rel_err": sum(errs) / len(errs)})

    return {"timing": timing_rows, "accuracy": accuracy_rows}


def _svg_line_chart(points, width=520, height=220, xlabel="", ylabel="", log_x=False, log_y=False, color="#5ea0ff"):
    import math as _m
    pad_l, pad_r, pad_t, pad_b = 46, 14, 14, 30
    plot_w, plot_h = width - pad_l - pad_r, height - pad_t - pad_b

    xs = [p[0] for p in points]
    ys = [p[1] for p in points]

    def tx(x):
        x = _m.log10(max(x, 1e-12)) if log_x else x
        lo = _m.log10(max(min(xs), 1e-12)) if log_x else min(xs)
        hi = _m.log10(max(xs)) if log_x else max(xs)
        span = (hi - lo) or 1
        return pad_l + (x - lo) / span * plot_w

    def ty(y):
        y = _m.log10(max(y, 1e-15)) if log_y else y
        lo = _m.log10(max(min(ys), 1e-15)) if log_y else min(ys)
        hi = _m.log10(max(ys)) if log_y else max(ys)
        span = (hi - lo) or 1
        return height - pad_b - (y - lo) / span * plot_h

    path = " ".join(f"{'M' if i == 0 else 'L'}{tx(x):.1f},{ty(y):.1f}" for i, (x, y) in enumerate(points))
    dots = "".join(f'<circle cx="{tx(x):.1f}" cy="{ty(y):.1f}" r="2.5" fill="{color}"/>' for x, y in points)

    return f'''<svg width="{width}" height="{height}" class="chart">
  <line x1="{pad_l}" y1="{pad_t}" x2="{pad_l}" y2="{height-pad_b}" stroke="#2a3245"/>
  <line x1="{pad_l}" y1="{height-pad_b}" x2="{width-pad_r}" y2="{height-pad_b}" stroke="#2a3245"/>
  <path d="{path}" fill="none" stroke="{color}" stroke-width="2"/>
  {dots}
  <text x="{width/2}" y="{height-6}" fill="#7d8aa3" font-size="11" text-anchor="middle">{xlabel}</text>
  <text x="12" y="{pad_t+4}" fill="#7d8aa3" font-size="11" text-anchor="start">{ylabel}</text>
</svg>'''


def render_benchmark_html(results, out_path, title="Barnes-Hut benchmark"):
    timing = results["timing"]
    accuracy = results["accuracy"]

    timing_chart_time = _svg_line_chart(
        [(r["n"], r["bruteforce_s"]) for r in timing], color="#ff9a5a",
        xlabel="N (log scale)", ylabel="seconds", log_x=True, log_y=True,
    )
    timing_chart_bh = _svg_line_chart(
        [(r["n"], r["barnes_hut_s"]) for r in timing], color="#5ea0ff",
        xlabel="N (log scale)", ylabel="seconds", log_x=True, log_y=True,
    )

    acc_by_n = {}
    for row in accuracy:
        acc_by_n.setdefault(row["n"], []).append((row["theta"], row["max_rel_err"]))
    acc_charts = ""
    for n, pts in acc_by_n.items():
        chart = _svg_line_chart(pts, color="#c792ea", xlabel="theta", ylabel="max rel. error", log_y=True)
        acc_charts += f'<div class="chart-card"><h3>Accuracy vs. theta (N={n})</h3>{chart}</div>'

    timing_rows_html = "".join(
        f'<tr><td>{r["n"]}</td><td>{r["bruteforce_s"]*1000:.3f} ms</td>'
        f'<td>{r["barnes_hut_s"]*1000:.3f} ms</td>'
        f'<td>{r["bruteforce_s"]/max(r["barnes_hut_s"],1e-9):.2f}x</td></tr>'
        for r in timing
    )
    accuracy_rows_html = "".join(
        f'<tr><td>{r["n"]}</td><td>{r["theta"]}</td><td>{r["max_rel_err"]:.4e}</td><td>{r["mean_rel_err"]:.4e}</td></tr>'
        for r in accuracy
    )

    html_doc = _BENCH_TEMPLATE.format(
        title=html_escape.escape(title),
        timing_chart_time=timing_chart_time,
        timing_chart_bh=timing_chart_bh,
        acc_charts=acc_charts,
        timing_rows=timing_rows_html,
        accuracy_rows=accuracy_rows_html,
    )
    with open(out_path, "w") as f:
        f.write(html_doc)
    return out_path


_BENCH_TEMPLATE = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Orrery — {title}</title>
<style>
  :root {{ color-scheme: dark; }}
  body {{ margin: 0; background: #0b0e14; color: #d8dee9; font-family: -apple-system, "Segoe UI", Roboto, sans-serif;
    padding: 28px 40px; }}
  h1 {{ font-size: 20px; color: #e8ecf4; }}
  h2 {{ font-size: 15px; color: #e8ecf4; margin-top: 34px; }}
  h3 {{ font-size: 12px; color: #9aa7c2; margin: 0 0 6px; }}
  p.sub {{ color: #7d8aa3; font-size: 13px; }}
  .row {{ display: flex; gap: 24px; flex-wrap: wrap; }}
  .card {{ background: #10151f; border: 1px solid #1c2230; border-radius: 8px; padding: 16px; }}
  .chart-card {{ background: #10151f; border: 1px solid #1c2230; border-radius: 8px; padding: 12px; }}
  table {{ border-collapse: collapse; font-size: 12px; margin-top: 8px; }}
  td, th {{ padding: 5px 12px; text-align: right; border-bottom: 1px solid #1c2230; }}
  th {{ color: #7d8aa3; font-weight: 500; }}
  td:first-child, th:first-child {{ text-align: left; }}
  .chart text {{ font-family: inherit; }}
</style>
</head>
<body>
<h1>{title}</h1>
<p class="sub">Direct O(N&sup2;) summation vs. Barnes-Hut octree approximation (&theta;=0.5 for timing), on random point clouds.</p>

<h2>Timing</h2>
<div class="row">
  <div class="card"><h3>Brute force (log/log)</h3>{timing_chart_time}</div>
  <div class="card"><h3>Barnes-Hut, &theta;=0.5 (log/log)</h3>{timing_chart_bh}</div>
</div>
<table>
<tr><th>N</th><th>Brute force</th><th>Barnes-Hut</th><th>Speedup</th></tr>
{timing_rows}
</table>

<h2>Accuracy vs. opening angle &theta;</h2>
<p class="sub">Max relative force-magnitude error against brute force, across a sweep of &theta;. &theta;=0 must be (near) exact.</p>
<div class="row">
{acc_charts}
</div>
<table>
<tr><th>N</th><th>theta</th><th>Max rel. error</th><th>Mean rel. error</th></tr>
{accuracy_rows}
</table>

</body>
</html>
"""
