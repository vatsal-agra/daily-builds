"""Self-contained HTML/Canvas replay viewer.

Generates one .html file with the run log embedded as inline JSON and a
small vanilla-JS canvas renderer -- no server, no build step, no external
dependencies. Open it in any browser.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any, Dict

from .slam import SlamConfig, SlamRun


def _payload(run: SlamRun, cfg: SlamConfig) -> Dict[str, Any]:
    return {
        "world": {
            "name": run.world.name,
            "width": run.world.width,
            "height": run.world.height,
            "walls": run.world.walls,
        },
        "resolution": cfg.resolution,
        "gridCols": run.grid.cols,
        "gridRows": run.grid.rows,
        "frames": [asdict(f) for f in run.frames],
        "snapshots": [{"t": t, "grid": g} for t, g in run.snapshots],
        "meta": {
            "mode": cfg.mode,
            "numParticles": cfg.num_particles,
            "seed": cfg.seed,
        },
    }


_HTML_TEMPLATE = r"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Beacon replay -- __WORLD__</title>
<style>
  :root {
    --bg: #0b0e14; --panel: #131826; --ink: #dbe4f0; --dim: #7c8aa6;
    --grid-free: #17324d; --grid-occ: #f2c14e; --grid-unknown: #10131c;
    --truth: #3a4a63; --true-robot: #33d17a; --est-robot: #ff6b6b;
    --particle: #5fb4ff; --beam: rgba(255, 209, 102, 0.35); --path: #b388ff;
    --accent: #5fb4ff;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--bg); color: var(--ink);
    font: 14px/1.4 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    display: flex; flex-direction: column; height: 100vh;
  }
  header {
    padding: 10px 16px; background: var(--panel); border-bottom: 1px solid #1f2637;
    display: flex; align-items: center; gap: 16px; flex-wrap: wrap;
  }
  header h1 { font-size: 15px; margin: 0; font-weight: 600; }
  header .sub { color: var(--dim); font-size: 12px; }
  main { flex: 1; display: flex; min-height: 0; }
  #canvasWrap { flex: 1; position: relative; overflow: hidden; }
  canvas { display: block; background: var(--grid-unknown); }
  aside {
    width: 260px; background: var(--panel); border-left: 1px solid #1f2637;
    padding: 14px; overflow-y: auto; flex-shrink: 0;
  }
  aside h2 { font-size: 12px; text-transform: uppercase; letter-spacing: .06em;
    color: var(--dim); margin: 18px 0 8px; }
  aside h2:first-child { margin-top: 0; }
  .stat { display: flex; justify-content: space-between; padding: 3px 0; font-size: 13px; }
  .stat b { font-variant-numeric: tabular-nums; }
  .legend { display: flex; align-items: center; gap: 8px; padding: 3px 0; font-size: 12.5px; color: var(--dim); }
  .swatch { width: 12px; height: 12px; border-radius: 3px; flex-shrink: 0; }
  label.toggle { display: flex; align-items: center; gap: 8px; padding: 4px 0; cursor: pointer; font-size: 13px; }
  .controls {
    padding: 10px 16px; background: var(--panel); border-top: 1px solid #1f2637;
    display: flex; align-items: center; gap: 12px;
  }
  button {
    background: #1c2436; color: var(--ink); border: 1px solid #2a3450; border-radius: 6px;
    padding: 6px 14px; cursor: pointer; font-size: 13px;
  }
  button:hover { background: #232d45; }
  input[type=range] { flex: 1; accent-color: var(--accent); }
  select {
    background: #1c2436; color: var(--ink); border: 1px solid #2a3450; border-radius: 6px;
    padding: 5px 8px; font-size: 12.5px;
  }
  #stepLabel { font-variant-numeric: tabular-nums; color: var(--dim); min-width: 92px; text-align: right; }
</style>
</head>
<body>
<header>
  <h1>Beacon &mdash; SLAM replay</h1>
  <span class="sub" id="headerSub"></span>
</header>
<main>
  <div id="canvasWrap"><canvas id="cv"></canvas></div>
  <aside>
    <h2>Frame</h2>
    <div class="stat">Step <b id="statStep">0</b></div>
    <div class="stat">Pose error <b id="statErr">--</b></div>
    <div class="stat">N<sub>eff</sub> <b id="statNeff">--</b></div>
    <div class="stat">Goals reached <b id="statGoals">--</b></div>
    <div class="stat">Bump <b id="statBump">--</b></div>

    <h2>Layers</h2>
    <label class="toggle"><input type="checkbox" id="toggleTruth" checked> Ground truth walls</label>
    <label class="toggle"><input type="checkbox" id="toggleGrid" checked> SLAM occupancy grid</label>
    <label class="toggle"><input type="checkbox" id="toggleParticles" checked> Particle cloud</label>
    <label class="toggle"><input type="checkbox" id="toggleBeams" checked> Lidar rays</label>
    <label class="toggle"><input type="checkbox" id="togglePath" checked> Planned path</label>
    <label class="toggle"><input type="checkbox" id="toggleTrail" checked> Pose trail</label>

    <h2>Legend</h2>
    <div class="legend"><span class="swatch" style="background:var(--true-robot)"></span> True pose</div>
    <div class="legend"><span class="swatch" style="background:var(--est-robot)"></span> SLAM estimate</div>
    <div class="legend"><span class="swatch" style="background:var(--particle)"></span> Particles</div>
    <div class="legend"><span class="swatch" style="background:var(--grid-occ)"></span> Believed occupied</div>
    <div class="legend"><span class="swatch" style="background:var(--truth)"></span> True wall</div>
    <div class="legend"><span class="swatch" style="background:var(--path)"></span> Planned path</div>

    <h2>Run</h2>
    <div class="stat">World <b id="metaWorld"></b></div>
    <div class="stat">Mode <b id="metaMode"></b></div>
    <div class="stat">Particles <b id="metaParticles"></b></div>
    <div class="stat">Total steps <b id="metaSteps"></b></div>
  </aside>
</main>
<div class="controls">
  <button id="playBtn">&#9658; Play</button>
  <span id="stepLabel">0 / 0</span>
  <input type="range" id="scrubber" min="0" max="0" value="0" step="1">
  <select id="speedSelect">
    <option value="240">0.5x</option>
    <option value="120" selected>1x</option>
    <option value="60">2x</option>
    <option value="20">6x</option>
  </select>
</div>
<script>
const DATA = __DATA_JSON__;

const cv = document.getElementById('cv');
const ctx = cv.getContext('2d');
const wrap = document.getElementById('canvasWrap');

function resize() {
  cv.width = wrap.clientWidth;
  cv.height = wrap.clientHeight;
  draw();
}
window.addEventListener('resize', resize);

const world = DATA.world;
const frames = DATA.frames;
const snapshots = DATA.snapshots;
const res = DATA.resolution;

document.getElementById('headerSub').textContent =
  `${world.name} world • ${world.width}×${world.height}m • ${frames.length} steps`;
document.getElementById('metaWorld').textContent = world.name;
document.getElementById('metaMode').textContent = DATA.meta.mode;
document.getElementById('metaParticles').textContent = DATA.meta.numParticles;
document.getElementById('metaSteps').textContent = frames.length;

let cur = 0;
let playing = false;
let playTimer = null;

const scrubber = document.getElementById('scrubber');
scrubber.max = Math.max(0, frames.length - 1);
const stepLabel = document.getElementById('stepLabel');
const playBtn = document.getElementById('playBtn');
const speedSelect = document.getElementById('speedSelect');

const toggles = {
  truth: document.getElementById('toggleTruth'),
  grid: document.getElementById('toggleGrid'),
  particles: document.getElementById('toggleParticles'),
  beams: document.getElementById('toggleBeams'),
  path: document.getElementById('togglePath'),
  trail: document.getElementById('toggleTrail'),
};
Object.values(toggles).forEach(el => el.addEventListener('change', draw));

function worldToPx(x, y) {
  const pad = 24;
  const scale = Math.min(
    (cv.width - 2 * pad) / world.width,
    (cv.height - 2 * pad) / world.height
  );
  return [pad + x * scale, pad + y * scale, scale];
}

function snapshotForFrame(t) {
  if (!snapshots.length) return null;
  let best = snapshots[0];
  for (const s of snapshots) {
    if (s.t <= t) best = s; else break;
  }
  return best;
}

function draw() {
  ctx.clearRect(0, 0, cv.width, cv.height);
  if (!frames.length) return;
  const f = frames[cur];
  const [, , scale] = worldToPx(0, 0);

  // -- occupancy grid heatmap --
  if (toggles.grid.checked) {
    const snap = snapshotForFrame(f.t);
    if (snap) {
      const g = snap.grid;
      const cell = res * scale;
      for (let r = 0; r < g.length; r++) {
        const row = g[r];
        for (let c = 0; c < row.length; c++) {
          const p = row[c];
          if (p > 0.35 && p < 0.65) continue; // unknown: leave as background
          const [px, py] = worldToPx(c * res, r * res);
          if (p >= 0.65) {
            const a = Math.min(1, (p - 0.65) / 0.35) * 0.9 + 0.1;
            ctx.fillStyle = `rgba(242,193,78,${a})`;
          } else {
            ctx.fillStyle = 'rgba(23,50,77,0.55)';
          }
          ctx.fillRect(px, py, cell + 0.6, cell + 0.6);
        }
      }
    }
  }

  // -- ground truth walls --
  if (toggles.truth.checked) {
    ctx.strokeStyle = '#3a4a63';
    ctx.lineWidth = 2;
    ctx.beginPath();
    for (const [[x1, y1], [x2, y2]] of world.walls) {
      const [px1, py1] = worldToPx(x1, y1);
      const [px2, py2] = worldToPx(x2, y2);
      ctx.moveTo(px1, py1);
      ctx.lineTo(px2, py2);
    }
    ctx.stroke();
  }

  // -- pose trail --
  if (toggles.trail.checked) {
    ctx.beginPath();
    for (let i = 0; i <= cur; i++) {
      const [px, py] = worldToPx(frames[i].true_pose[0], frames[i].true_pose[1]);
      if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
    }
    ctx.strokeStyle = 'rgba(51,209,122,0.35)';
    ctx.lineWidth = 1.5;
    ctx.stroke();

    ctx.beginPath();
    for (let i = 0; i <= cur; i++) {
      const [px, py] = worldToPx(frames[i].est_pose[0], frames[i].est_pose[1]);
      if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
    }
    ctx.strokeStyle = 'rgba(255,107,107,0.35)';
    ctx.lineWidth = 1.5;
    ctx.stroke();
  }

  // -- planned path --
  if (toggles.path.checked && f.path_world.length > 1) {
    ctx.beginPath();
    f.path_world.forEach(([x, y], i) => {
      const [px, py] = worldToPx(x, y);
      if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
    });
    ctx.strokeStyle = '#b388ff';
    ctx.lineWidth = 1.5;
    ctx.setLineDash([4, 4]);
    ctx.stroke();
    ctx.setLineDash([]);
  }

  // -- lidar rays (from true pose, since that's what "really" fired) --
  if (toggles.beams.checked) {
    const [ox, oy] = worldToPx(f.true_pose[0], f.true_pose[1]);
    ctx.strokeStyle = 'rgba(255,209,102,0.25)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (const [ex, ey] of f.beam_endpoints) {
      const [px, py] = worldToPx(ex, ey);
      ctx.moveTo(ox, oy);
      ctx.lineTo(px, py);
    }
    ctx.stroke();
  }

  // -- particle cloud --
  if (toggles.particles.checked) {
    ctx.fillStyle = 'rgba(95,180,255,0.6)';
    for (const [px_, py_] of f.particles) {
      const [px, py] = worldToPx(px_, py_);
      ctx.beginPath();
      ctx.arc(px, py, 1.6, 0, 2 * Math.PI);
      ctx.fill();
    }
  }

  // -- true pose --
  drawRobot(f.true_pose, '#33d17a');
  // -- estimated pose --
  drawRobot(f.est_pose, '#ff6b6b');

  if (f.collided) {
    const [px, py] = worldToPx(f.true_pose[0], f.true_pose[1]);
    ctx.strokeStyle = '#ff3b3b';
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(px, py, 12, 0, 2 * Math.PI);
    ctx.stroke();
  }

  updateHud(f);
}

function drawRobot(pose, color) {
  const [px, py] = worldToPx(pose[0], pose[1]);
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.arc(px, py, 5, 0, 2 * Math.PI);
  ctx.fill();
  ctx.strokeStyle = color;
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(px, py);
  ctx.lineTo(px + 12 * Math.cos(pose[2]), py + 12 * Math.sin(pose[2]));
  ctx.stroke();
}

function updateHud(f) {
  const dx = f.true_pose[0] - f.est_pose[0];
  const dy = f.true_pose[1] - f.est_pose[1];
  const err = Math.hypot(dx, dy);
  document.getElementById('statStep').textContent = f.t;
  document.getElementById('statErr').textContent = err.toFixed(2) + ' m';
  document.getElementById('statNeff').textContent = f.neff.toFixed(0);
  document.getElementById('statGoals').textContent = f.goal_reached_count;
  document.getElementById('statBump').textContent = f.collided ? 'yes' : 'no';
  stepLabel.textContent = `${cur} / ${frames.length - 1}`;
  scrubber.value = cur;
}

scrubber.addEventListener('input', () => {
  cur = parseInt(scrubber.value, 10);
  draw();
});

playBtn.addEventListener('click', () => {
  playing = !playing;
  playBtn.innerHTML = playing ? '&#10074;&#10074; Pause' : '&#9658; Play';
  if (playing) schedule(); else clearTimeout(playTimer);
});

function schedule() {
  playTimer = setTimeout(() => {
    if (!playing) return;
    cur = Math.min(frames.length - 1, cur + 1);
    draw();
    if (cur >= frames.length - 1) {
      playing = false;
      playBtn.innerHTML = '&#9658; Play';
      return;
    }
    schedule();
  }, parseInt(speedSelect.value, 10));
}

resize();
draw();
</script>
</body>
</html>
"""


def render(run: SlamRun, cfg: SlamConfig, out_path: str) -> str:
    payload = _payload(run, cfg)
    html = _HTML_TEMPLATE.replace("__WORLD__", run.world.name)
    html = html.replace("__DATA_JSON__", json.dumps(payload))
    with open(out_path, "w") as f:
        f.write(html)
    return out_path
