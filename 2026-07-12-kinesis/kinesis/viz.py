"""Self-contained HTML visualizers: an animated canvas replay of one
recorded simulation trace, a static gallery grid of a whole population's
rest poses, and a fitness-over-generations line chart. No CDN, no
external assets -- everything is inlined into the returned HTML string.
"""
import json
import html as html_lib

from .genome import Genome
from .body import build_phenotype

_BASE_CSS = """
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body {
  margin: 0; padding: 24px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  background: #0f1218; color: #e8ecf1;
}
h1 { font-size: 20px; font-weight: 600; margin: 0 0 4px 0; }
.subtitle { color: #8b93a3; font-size: 13px; margin-bottom: 20px; }
.panel { background: #171c26; border: 1px solid #262e3d; border-radius: 12px; padding: 16px; }
canvas { display: block; background: #0a0d13; border-radius: 8px; width: 100%; }
.controls { display: flex; align-items: center; gap: 12px; margin-top: 12px; flex-wrap: wrap; }
button {
  background: #2b3547; color: #e8ecf1; border: 1px solid #3a4559; border-radius: 8px;
  padding: 8px 16px; font-size: 13px; cursor: pointer;
}
button:hover { background: #364154; }
input[type=range] { flex: 1; min-width: 160px; }
.stat { font-variant-numeric: tabular-nums; font-size: 13px; color: #b7c0d1; }
.stat b { color: #e8ecf1; }
.grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr));
  gap: 14px; margin-top: 16px;
}
.card { background: #171c26; border: 1px solid #262e3d; border-radius: 10px; padding: 10px; }
.card canvas { height: 130px; }
.card .rank { font-size: 12px; color: #8b93a3; }
.card .fit { font-size: 15px; font-weight: 600; margin: 2px 0; }
.card .meta { font-size: 11px; color: #6b7385; }
"""


def _page(title, body_html, extra_css=""):
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{html_lib.escape(title)}</title>
<style>{_BASE_CSS}{extra_css}</style></head>
<body>{body_html}</body></html>"""


def render_replay(genome, result, title="Kinesis replay", fitness_hint=None):
    trace = result.trace
    dims = result.body_dims
    frames_json = json.dumps(trace)
    dims_json = json.dumps(dims)
    fit_line = ""
    if fitness_hint is not None:
        fit_line = f'<div class="stat">recorded fitness: <b>{fitness_hint:.3f}</b></div>'

    body_html = f"""
<h1>{html_lib.escape(title)}</h1>
<div class="subtitle">distance {result.distance:.2f} m &middot; energy {result.energy:.0f} &middot;
{'toppled' if result.toppled else 'stayed upright'} &middot; {result.duration_simulated:.1f}s simulated</div>
<div class="panel">
  <canvas id="stage" width="960" height="420"></canvas>
  <div class="controls">
    <button id="playBtn">Pause</button>
    <input id="scrub" type="range" min="0" max="{max(0, len(trace) - 1)}" value="0">
    <span class="stat">t=<b id="tval">0.00</b>s &nbsp; x=<b id="xval">0.00</b>m</span>
  </div>
  {fit_line}
</div>
<script>
const frames = {frames_json};
const dims = {dims_json};
const canvas = document.getElementById('stage');
const ctx = canvas.getContext('2d');
const scrub = document.getElementById('scrub');
const playBtn = document.getElementById('playBtn');
const tval = document.getElementById('tval');
const xval = document.getElementById('xval');
let idx = 0;
let playing = frames.length > 0;
const PPM = 60; // pixels per meter

function draw(i) {{
  if (!frames.length) return;
  const [t, bodies] = frames[i];
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  const torsoX = bodies[0][0];
  const camX = torsoX * PPM - canvas.width * 0.35;

  // ground
  const groundScreenY = canvas.height - 60;
  ctx.strokeStyle = '#3a4559';
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(0, groundScreenY);
  ctx.lineTo(canvas.width, groundScreenY);
  ctx.stroke();
  ctx.fillStyle = '#8b93a3';
  ctx.font = '11px monospace';
  for (let gx = Math.floor((camX/PPM)/1)*1 - 2; gx < (camX + canvas.width)/PPM + 2; gx++) {{
    const sx = gx * PPM - camX;
    ctx.beginPath(); ctx.moveTo(sx, groundScreenY); ctx.lineTo(sx, groundScreenY + 6); ctx.stroke();
    ctx.fillText(gx + 'm', sx - 8, groundScreenY + 18);
  }}

  for (let b = 0; b < bodies.length; b++) {{
    const [x, y, angle] = bodies[b];
    const [hl, hw] = dims[b];
    const sx = x * PPM - camX;
    const sy = groundScreenY - y * PPM;
    ctx.save();
    ctx.translate(sx, sy);
    ctx.rotate(-angle);
    ctx.fillStyle = b === 0 ? '#5aa9e6' : '#7fd99a';
    ctx.strokeStyle = '#0a0d13';
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.rect(-hl * PPM, -hw * PPM, hl * 2 * PPM, hw * 2 * PPM);
    ctx.fill();
    ctx.stroke();
    ctx.restore();
  }}

  tval.textContent = t.toFixed(2);
  xval.textContent = torsoX.toFixed(2);
  scrub.value = i;
}}

function tick() {{
  if (playing && frames.length) {{
    idx = (idx + 1) % frames.length;
    draw(idx);
  }}
  requestAnimationFrame(tick);
}}

scrub.addEventListener('input', () => {{ playing = false; playBtn.textContent = 'Play'; idx = +scrub.value; draw(idx); }});
playBtn.addEventListener('click', () => {{
  playing = !playing;
  playBtn.textContent = playing ? 'Pause' : 'Play';
}});

if (frames.length) draw(0);
else {{
  ctx.fillStyle = '#8b93a3';
  ctx.font = '14px sans-serif';
  ctx.fillText('No frames recorded (creature toppled at t=0?)', 20, 40);
}}
requestAnimationFrame(tick);
</script>
"""
    return _page(title, body_html)


def _rest_pose_svg(genome, width=170, height=120):
    phenotype = build_phenotype(genome)
    xs, ys = [], []
    for b in phenotype.bodies:
        for c in b.corners():
            xs.append(c[0])
            ys.append(c[1])
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    span_x = max(max_x - min_x, 0.2)
    span_y = max(max_y - min_y, 0.2)
    scale = min((width - 16) / span_x, (height - 16) / span_y)
    cx = (min_x + max_x) / 2.0
    cy = (min_y + max_y) / 2.0

    def to_screen(pt):
        return (width / 2 + (pt[0] - cx) * scale, height / 2 - (pt[1] - cy) * scale)

    parts = [f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
             f'xmlns="http://www.w3.org/2000/svg">']
    parts.append(f'<rect width="{width}" height="{height}" fill="#0a0d13" rx="6"/>')
    for i, b in enumerate(phenotype.bodies):
        pts = [to_screen(c) for c in b.corners()]
        poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        color = "#5aa9e6" if i == 0 else "#7fd99a"
        parts.append(f'<polygon points="{poly}" fill="{color}" stroke="#0a0d13" stroke-width="1"/>')
    parts.append("</svg>")
    return "".join(parts)


def render_gallery(population_dict, label):
    individuals = population_dict["individuals"]
    ranked = sorted(individuals, key=lambda ind: ind["fitness"], reverse=True)
    cards = []
    for rank, item in enumerate(ranked):
        genome = Genome.from_dict(item["genome"])
        svg = _rest_pose_svg(genome)
        cards.append(f"""
<div class="card">
  {svg}
  <div class="rank">#{rank + 1}</div>
  <div class="fit">{item['fitness']:.2f} fitness</div>
  <div class="meta">dist {item['distance']:.2f}m &middot; nodes {genome.node_count()} &middot;
  {'toppled' if item['toppled'] else 'upright'}</div>
</div>""")
    body_html = f"""
<h1>Population gallery &mdash; {html_lib.escape(label)}</h1>
<div class="subtitle">generation {population_dict['generation']} &middot; {len(individuals)} creatures,
sorted best first</div>
<div class="grid">{''.join(cards)}</div>
"""
    return _page(f"Kinesis gallery: {label}", body_html)


def render_fitness_chart(history, label):
    gens = [h["generation"] for h in history]
    best = [h["best"] for h in history]
    mean = [h["mean"] for h in history]
    worst = [h["worst"] for h in history]
    data_json = json.dumps({"gens": gens, "best": best, "mean": mean, "worst": worst})
    body_html = f"""
<h1>Fitness over generations &mdash; {html_lib.escape(label)}</h1>
<div class="subtitle">{len(history)} generations recorded</div>
<div class="panel"><canvas id="chart" width="900" height="420"></canvas></div>
<script>
const d = {data_json};
const canvas = document.getElementById('chart');
const ctx = canvas.getContext('2d');
const pad = 50;
const w = canvas.width - pad * 2, h = canvas.height - pad * 2;
const allY = d.best.concat(d.mean).concat(d.worst);
const yMin = Math.min(...allY), yMax = Math.max(...allY);
const yRange = (yMax - yMin) || 1;
const n = d.gens.length;

function xAt(i) {{ return pad + (n <= 1 ? 0 : (i / (n - 1)) * w); }}
function yAt(v) {{ return pad + h - ((v - yMin) / yRange) * h; }}

ctx.strokeStyle = '#262e3d';
ctx.beginPath(); ctx.moveTo(pad, pad); ctx.lineTo(pad, pad + h); ctx.lineTo(pad + w, pad + h); ctx.stroke();
ctx.fillStyle = '#8b93a3'; ctx.font = '11px monospace';
ctx.fillText(yMax.toFixed(2), 4, pad + 4);
ctx.fillText(yMin.toFixed(2), 4, pad + h + 4);
ctx.fillText('gen 0', pad - 4, pad + h + 18);
ctx.fillText('gen ' + (n - 1), pad + w - 30, pad + h + 18);

function plot(series, color) {{
  ctx.strokeStyle = color; ctx.lineWidth = 2; ctx.beginPath();
  series.forEach((v, i) => {{
    const x = xAt(i), y = yAt(v);
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  }});
  ctx.stroke();
}}
plot(d.worst, '#e67e7e');
plot(d.mean, '#e6c05a');
plot(d.best, '#5aa9e6');

ctx.fillStyle = '#5aa9e6'; ctx.fillText('best', pad + w - 34, pad + 12);
ctx.fillStyle = '#e6c05a'; ctx.fillText('mean', pad + w - 34, pad + 26);
ctx.fillStyle = '#e67e7e'; ctx.fillText('worst', pad + w - 34, pad + 40);
</script>
"""
    return _page(f"Kinesis fitness chart: {label}", body_html)
