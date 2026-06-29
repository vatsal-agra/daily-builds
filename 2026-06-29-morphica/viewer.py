"""
Interactive browser viewer — generates a self-contained single-file HTML
that animates L-systems growing step-by-step and attractors building up.
"""
import base64
import json


_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Morphica — Generative Art Viewer</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: #0a0a0f; color: #e0e0e0; font-family: 'Segoe UI', system-ui, sans-serif; }
  header { background: #111122; border-bottom: 1px solid #2a2a4a; padding: 12px 20px;
           display: flex; align-items: center; gap: 16px; }
  header h1 { font-size: 1.4rem; color: #88aaff; letter-spacing: 0.08em; }
  header p { color: #778; font-size: 0.85rem; }
  .controls { background: #111122; padding: 10px 20px; display: flex; flex-wrap: wrap;
              gap: 10px; align-items: center; border-bottom: 1px solid #2a2a4a; }
  .controls label { color: #aab; font-size: 0.8rem; display: flex; flex-direction: column; gap: 3px; }
  .controls select, .controls input[type=range], .controls input[type=number] {
      background: #1a1a2e; border: 1px solid #3a3a6a; color: #dde;
      border-radius: 4px; padding: 4px 8px; font-size: 0.85rem; }
  .controls button { background: #2244aa; border: none; color: #ddf; border-radius: 5px;
      padding: 6px 14px; cursor: pointer; font-size: 0.85rem; transition: background 0.15s; }
  .controls button:hover { background: #3355cc; }
  .controls button.active { background: #44aaff; color: #001; }
  #status { color: #8ae; font-size: 0.8rem; margin-left: auto; }
  .gallery { display: flex; flex-wrap: wrap; gap: 16px; padding: 20px;
             justify-content: center; }
  .card { background: #111122; border: 1px solid #2a2a4a; border-radius: 8px;
          overflow: hidden; width: 380px; }
  .card h3 { padding: 8px 12px; font-size: 0.9rem; color: #aac; background: #0e0e1e;
              border-bottom: 1px solid #2a2a4a; }
  canvas { display: block; width: 100%; }
  img.artwork { display: block; width: 100%; }
  .card-footer { padding: 6px 12px; font-size: 0.75rem; color: #668; background: #0e0e1e;
                  border-top: 1px solid #2a2a4a; display: flex; gap: 10px; align-items: center; }
  .card-footer button { background: #1a3a6a; border: none; color: #aac; border-radius: 3px;
      padding: 3px 8px; cursor: pointer; font-size: 0.75rem; }
  #animator { background: #111; border: 1px solid #224; border-radius: 8px; margin: 20px auto;
               max-width: 820px; }
  #animator h3 { padding: 10px 16px; color: #8af; border-bottom: 1px solid #224; }
  #anim-canvas { display: block; margin: 0 auto; }
  #anim-controls { padding: 10px 16px; display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
  #progress { flex: 1; appearance: none; height: 6px; background: #224; border-radius: 3px; }
  #progress::-webkit-slider-thumb { appearance: none; width: 14px; height: 14px;
    border-radius: 50%; background: #44aaff; cursor: pointer; }
</style>
</head>
<body>

<header>
  <div>
    <h1>✦ Morphica</h1>
    <p>Generative Algorithmic Art Engine</p>
  </div>
  <span id="status">Loaded ✓</span>
</header>

<div class="controls">
  <label>L-System
    <select id="ls-select">__LS_OPTIONS__</select>
  </label>
  <label>Iterations
    <input type="number" id="ls-iter" value="5" min="1" max="8" style="width:60px">
  </label>
  <label>Stroke colour
    <input type="color" id="ls-color" value="#00cfff">
  </label>
  <button onclick="runLSystem()">▶ Render L-System</button>

  <label>Attractor
    <select id="att-select">__ATT_OPTIONS__</select>
  </label>
  <button onclick="renderAttractor()">▶ Render Attractor</button>

  <button id="anim-btn" onclick="toggleAnim()">▶ Animate</button>
</div>

<div id="animator">
  <h3 id="anim-title">L-System Growth Animation</h3>
  <canvas id="anim-canvas" width="780" height="500"></canvas>
  <div id="anim-controls">
    <button onclick="animStep(-1)">◀</button>
    <input type="range" id="progress" min="0" max="100" value="0" oninput="seekAnim(this.value)">
    <button onclick="animStep(1)">▶</button>
    <span id="anim-info" style="color:#88a;font-size:0.8rem"></span>
    <button onclick="exportFrame()" style="margin-left:auto">💾 Export PNG</button>
  </div>
</div>

<div class="gallery" id="gallery">
__GALLERY__
</div>

<script>
const DATA = __DATA_JSON__;

let animTimer = null;
let animFrames = [];
let animIdx = 0;

// ── gallery images already embedded ──────────────────────────────────────────
function buildGallery() {
  const g = document.getElementById('gallery');
  DATA.gallery.forEach(item => {
    const card = document.createElement('div');
    card.className = 'card';
    card.innerHTML = `<h3>${item.title}</h3>
      <img class="artwork" src="data:image/png;base64,${item.b64}" alt="${item.title}">
      <div class="card-footer"><span>${item.desc}</span>
        <button onclick="downloadImg('${item.title}','${item.b64}')">💾</button>
      </div>`;
    g.appendChild(card);
  });
}

function downloadImg(name, b64) {
  const a = document.createElement('a');
  a.href = 'data:image/png;base64,' + b64;
  a.download = name.replace(/\s+/g,'_') + '.png';
  a.click();
}

// ── L-system canvas rendering ─────────────────────────────────────────────────
function runLSystem() {
  const name = document.getElementById('ls-select').value;
  const iters = parseInt(document.getElementById('ls-iter').value) || 5;
  const color = document.getElementById('ls-color').value;
  const ls = DATA.lsystems[name];
  if (!ls) return;
  const frames = growFrames(ls, iters);
  animFrames = frames;
  animIdx = frames.length - 1;
  drawFrame(frames[animIdx]);
  document.getElementById('anim-title').textContent = `L-System: ${name} (iter ${iters})`;
  document.getElementById('progress').max = frames.length - 1;
  document.getElementById('progress').value = animIdx;
  document.getElementById('anim-info').textContent = `Step ${animIdx+1}/${frames.length}`;
  document.getElementById('status').textContent = `${name} rendered ✓`;
}

function growFrames(ls, maxIter) {
  // Build string incrementally
  const frames = [];
  let s = ls.axiom;
  frames.push({ string: s, iter: 0 });
  for (let i = 0; i < maxIter; i++) {
    let ns = '';
    for (const ch of s) {
      const rule = ls.rules[ch];
      ns += (rule !== undefined) ? rule : ch;
    }
    s = ns;
    frames.push({ string: s, iter: i + 1 });
  }
  return frames;
}

function drawFrame(frame) {
  const canvas = document.getElementById('anim-canvas');
  const ctx = canvas.getContext('2d');
  const W = canvas.width, H = canvas.height;
  ctx.fillStyle = '#0a0a0f';
  ctx.fillRect(0, 0, W, H);

  const ls = DATA.lsystems[document.getElementById('ls-select').value];
  const color = document.getElementById('ls-color').value;
  const angle = ls ? ls.angle_deg : 90;
  const step = 8;

  const paths = turtlePaths(frame.string, angle, step);
  if (!paths.length) return;

  // Compute bounding box
  let xmin=Infinity,ymin=Infinity,xmax=-Infinity,ymax=-Infinity;
  for (const path of paths) for (const [x,y] of path) {
    xmin=Math.min(xmin,x); ymin=Math.min(ymin,y);
    xmax=Math.max(xmax,x); ymax=Math.max(ymax,y);
  }
  const bw = xmax-xmin||1, bh = ymax-ymin||1;
  const margin = 20;
  const scale = Math.min((W-2*margin)/bw, (H-2*margin)/bh);
  const tx = x => margin + (x-xmin)*scale;
  const ty = y => margin + (y-ymin)*scale;

  ctx.strokeStyle = color;
  ctx.lineWidth = Math.max(0.5, 1.5 - frame.iter * 0.2);
  ctx.lineCap = 'round';
  for (const path of paths) {
    if (path.length < 2) continue;
    ctx.beginPath();
    ctx.moveTo(tx(path[0][0]), ty(path[0][1]));
    for (let i=1;i<path.length;i++) ctx.lineTo(tx(path[i][0]), ty(path[i][1]));
    ctx.stroke();
  }
}

function turtlePaths(str, angleDeg, step) {
  const angleRad = angleDeg * Math.PI / 180;
  let x=0, y=0, heading=Math.PI/2;
  const stack = [];
  const paths = [];
  let cur = [[x,y]];

  for (const ch of str) {
    if (ch==='F'||ch==='G') {
      const nx = x + step * Math.cos(heading);
      const ny = y - step * Math.sin(heading);
      cur.push([nx,ny]); x=nx; y=ny;
    } else if (ch==='f') {
      if (cur.length>=2) paths.push(cur);
      x += step*Math.cos(heading); y -= step*Math.sin(heading);
      cur = [[x,y]];
    } else if (ch==='+') { heading += angleRad; }
    else if (ch==='-') { heading -= angleRad; }
    else if (ch==='|') { heading += Math.PI; }
    else if (ch==='[') { stack.push([x,y,heading,[...cur]]); }
    else if (ch===']') {
      if (cur.length>=2) paths.push(cur);
      if (stack.length) [x,y,heading,cur] = stack.pop();
    }
  }
  if (cur.length>=2) paths.push(cur);
  return paths;
}

// ── animation ─────────────────────────────────────────────────────────────────
let playing = false;
function toggleAnim() {
  playing = !playing;
  document.getElementById('anim-btn').classList.toggle('active', playing);
  document.getElementById('anim-btn').textContent = playing ? '⏸ Pause' : '▶ Animate';
  if (playing) scheduleNext();
}

function scheduleNext() {
  if (!playing || !animFrames.length) return;
  animIdx = (animIdx + 1) % animFrames.length;
  drawFrame(animFrames[animIdx]);
  document.getElementById('progress').value = animIdx;
  document.getElementById('anim-info').textContent = `Step ${animIdx+1}/${animFrames.length}`;
  animTimer = setTimeout(scheduleNext, 600);
}

function animStep(d) {
  if (!animFrames.length) return;
  animIdx = Math.max(0, Math.min(animFrames.length-1, animIdx+d));
  drawFrame(animFrames[animIdx]);
  document.getElementById('progress').value = animIdx;
}

function seekAnim(v) {
  if (!animFrames.length) return;
  animIdx = parseInt(v);
  drawFrame(animFrames[animIdx]);
}

function exportFrame() {
  const canvas = document.getElementById('anim-canvas');
  const a = document.createElement('a');
  a.href = canvas.toDataURL('image/png');
  a.download = 'morphica_frame.png';
  a.click();
}

// ── attractor placeholder ────────────────────────────────────────────────────
function renderAttractor() {
  const name = document.getElementById('att-select').value;
  const item = DATA.gallery.find(g => g.key === name);
  if (!item) { alert('Attractor image not in gallery — render via CLI first.'); return; }
  const canvas = document.getElementById('anim-canvas');
  const ctx = canvas.getContext('2d');
  const img = new Image();
  img.onload = () => {
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
  };
  img.src = 'data:image/png;base64,' + item.b64;
  document.getElementById('anim-title').textContent = `Attractor: ${name}`;
}

// ── init ──────────────────────────────────────────────────────────────────────
buildGallery();
// Auto-render first L-system
if (Object.keys(DATA.lsystems).length) runLSystem();
</script>
</body>
</html>
"""


def build_viewer(
    gallery_items,   # list of {title, desc, b64_png, key}
    lsystem_data,    # dict of name -> {axiom, rules, angle_deg}
    attractor_names, # list of attractor names for dropdown
    ls_names,        # list of l-system preset names
):
    """Build a self-contained HTML viewer string."""
    ls_options = "\n".join(
        f'<option value="{n}">{n}</option>' for n in ls_names
    )
    att_options = "\n".join(
        f'<option value="{n}">{n}</option>' for n in attractor_names
    )

    data_obj = {
        "gallery": gallery_items,
        "lsystems": lsystem_data,
    }

    html = _HTML_TEMPLATE
    html = html.replace("__LS_OPTIONS__", ls_options)
    html = html.replace("__ATT_OPTIONS__", att_options)
    html = html.replace("__GALLERY__", "")  # populated by JS
    html = html.replace("__DATA_JSON__", json.dumps(data_obj))
    return html
