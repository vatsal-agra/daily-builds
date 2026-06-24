"""
Interactive single-file HTML scene editor served over a local HTTP server.
The browser sends the JSON scene to Python, Python renders it, returns PNG.
Also includes a JS-only sphere-only fast preview (~50ms).
"""
import os
import sys
import json
import time
import base64
import threading
import http.server
import urllib.parse
import io
import traceback

_EDITOR_HTML = None  # generated lazily


def _build_html():
    return r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Lumina — Scene Editor</title>
<style>
  :root {
    --bg: #0d1117; --surface: #161b22; --border: #30363d;
    --text: #c9d1d9; --accent: #58a6ff; --green: #3fb950;
    --red: #f85149; --yellow: #d29922; --mono: 'JetBrains Mono', 'Fira Code', monospace;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: var(--bg); color: var(--text); font-family: var(--mono);
         font-size: 13px; height: 100vh; display: flex; flex-direction: column; }
  #header { padding: 10px 16px; border-bottom: 1px solid var(--border);
            display: flex; align-items: center; gap: 12px; }
  #header h1 { font-size: 16px; color: var(--accent); font-weight: 700;
               letter-spacing: 2px; }
  #header .subtitle { color: #8b949e; font-size: 11px; }
  .btn { padding: 5px 14px; border-radius: 6px; border: none; cursor: pointer;
         font-family: var(--mono); font-size: 12px; font-weight: 600;
         transition: opacity 0.15s; }
  .btn:hover { opacity: 0.8; }
  .btn-primary { background: var(--accent); color: #0d1117; }
  .btn-secondary { background: var(--surface); color: var(--text);
                   border: 1px solid var(--border); }
  .btn-green { background: var(--green); color: #0d1117; }
  #main { display: flex; flex: 1; overflow: hidden; }
  #editor-pane { width: 420px; min-width: 300px; display: flex; flex-direction: column;
                 border-right: 1px solid var(--border); }
  #scene-label { padding: 6px 12px; background: var(--surface);
                 border-bottom: 1px solid var(--border);
                 font-size: 11px; color: #8b949e; display: flex;
                 justify-content: space-between; align-items: center; }
  #scene-json { flex: 1; background: #0d1117; color: #c9d1d9; border: none;
                padding: 12px; font-family: var(--mono); font-size: 12px;
                resize: none; outline: none; line-height: 1.6; }
  #render-pane { flex: 1; display: flex; flex-direction: column; }
  #render-toolbar { padding: 8px 12px; background: var(--surface);
                    border-bottom: 1px solid var(--border);
                    display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
  #render-toolbar label { color: #8b949e; font-size: 11px; }
  #render-toolbar select, #render-toolbar input[type=number] {
    background: var(--bg); color: var(--text); border: 1px solid var(--border);
    border-radius: 4px; padding: 3px 7px; font-family: var(--mono);
    font-size: 12px; width: 80px; }
  #canvas-wrap { flex: 1; display: flex; align-items: center; justify-content: center;
                 background: #060a10; padding: 20px; overflow: auto; }
  #render-canvas { image-rendering: pixelated; border: 1px solid var(--border);
                   border-radius: 4px; max-width: 100%; max-height: 100%;
                   box-shadow: 0 8px 40px rgba(0,0,0,0.7); }
  #status-bar { padding: 6px 12px; background: var(--surface);
                border-top: 1px solid var(--border);
                font-size: 11px; color: #8b949e; }
  #status-bar .ok   { color: var(--green); }
  #status-bar .err  { color: var(--red); }
  #status-bar .warn { color: var(--yellow); }
  #scene-select { background: var(--bg); color: var(--text); border: 1px solid var(--border);
                  border-radius: 4px; padding: 3px 7px; font-family: var(--mono); font-size: 12px; }
  .sep { flex: 1; }
</style>
</head>
<body>
<div id="header">
  <h1>⬡ LUMINA</h1>
  <span class="subtitle">Ray Tracer · Path Tracer · Scene Editor</span>
  <div class="sep"></div>
  <select id="scene-select">
    <option value="spheres">Spheres</option>
    <option value="cornell">Cornell Box</option>
    <option value="dof">Depth of Field</option>
    <option value="whitted_demo">Whitted Demo</option>
  </select>
  <button class="btn btn-secondary" onclick="loadScene()">Load</button>
</div>
<div id="main">
  <div id="editor-pane">
    <div id="scene-label">
      <span>scene.json</span>
      <span id="json-status">●</span>
    </div>
    <textarea id="scene-json" spellcheck="false"></textarea>
  </div>
  <div id="render-pane">
    <div id="render-toolbar">
      <label>Mode</label>
      <select id="opt-mode">
        <option value="path">Path Tracer</option>
        <option value="whitted">Whitted</option>
      </select>
      <label>SPP</label>
      <input type="number" id="opt-spp" value="16" min="1" max="512" step="1">
      <label>Tonemap</label>
      <select id="opt-tonemap">
        <option value="aces">ACES</option>
        <option value="reinhard">Reinhard</option>
        <option value="clamp">Clamp</option>
      </select>
      <div class="sep"></div>
      <button class="btn btn-secondary" onclick="jsPreview()">⚡ JS Preview</button>
      <button class="btn btn-primary" onclick="pythonRender()">▶ Render</button>
    </div>
    <div id="canvas-wrap">
      <canvas id="render-canvas" width="400" height="225"></canvas>
    </div>
    <div id="status-bar"><span id="status-msg">Ready — click Render to trace.</span></div>
  </div>
</div>

<script>
// ─── JSON editor validation ──────────────────────────────────────────────────
const textarea = document.getElementById('scene-json');
const jsonStatus = document.getElementById('json-status');
textarea.addEventListener('input', () => {
  try { JSON.parse(textarea.value); jsonStatus.style.color = '#3fb950'; jsonStatus.title = 'Valid JSON'; }
  catch(e) { jsonStatus.style.color = '#f85149'; jsonStatus.title = e.message; }
});

// ─── Scene presets ───────────────────────────────────────────────────────────
const SCENES = {};

async function loadScene() {
  const name = document.getElementById('scene-select').value;
  const resp = await fetch('/scene/' + name);
  if (!resp.ok) { setStatus('Failed to load scene', 'err'); return; }
  const text = await resp.text();
  textarea.value = text;
  textarea.dispatchEvent(new Event('input'));
}

// ─── Python render ───────────────────────────────────────────────────────────
async function pythonRender() {
  let sceneJson;
  try { sceneJson = JSON.parse(textarea.value); }
  catch(e) { setStatus('JSON parse error: ' + e.message, 'err'); return; }

  const mode   = document.getElementById('opt-mode').value;
  const spp    = parseInt(document.getElementById('opt-spp').value);
  const tonemap = document.getElementById('opt-tonemap').value;

  sceneJson.render = sceneJson.render || {};
  sceneJson.render.mode    = mode;
  sceneJson.render.samples = spp;
  sceneJson.render.tonemap = tonemap;

  setStatus('Rendering... (this may take a moment)', 'warn');
  const t0 = performance.now();

  try {
    const resp = await fetch('/render', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(sceneJson),
    });
    if (!resp.ok) {
      const err = await resp.text();
      setStatus('Render error: ' + err, 'err');
      return;
    }
    const data = await resp.json();
    const elapsed = ((performance.now() - t0) / 1000).toFixed(2);

    const img = new Image();
    img.onload = () => {
      const canvas = document.getElementById('render-canvas');
      canvas.width  = data.width;
      canvas.height = data.height;
      const ctx = canvas.getContext('2d');
      ctx.drawImage(img, 0, 0);
      setStatus(`Rendered ${data.width}×${data.height} @ ${spp}spp in ${elapsed}s — ${data.rays_per_sec} rays/s`, 'ok');
    };
    img.src = 'data:image/png;base64,' + data.png_b64;
  } catch(e) {
    setStatus('Network error: ' + e.message, 'err');
  }
}

// ─── JS Preview (sphere-only, ~50 ms) ────────────────────────────────────────
function jsPreview() {
  let sceneJson;
  try { sceneJson = JSON.parse(textarea.value); }
  catch(e) { setStatus('JSON parse error: ' + e.message, 'err'); return; }

  const W = (sceneJson.render && sceneJson.render.width)  || 200;
  const H = (sceneJson.render && sceneJson.render.height) || 112;
  const spp = 4;

  setStatus('JS preview rendering…', 'warn');
  const t0 = performance.now();

  // Simple sphere-only path tracer in JS
  const canvas = document.getElementById('render-canvas');
  canvas.width  = W;
  canvas.height = H;
  const ctx = canvas.getContext('2d');
  const img = ctx.createImageData(W, H);

  const spheres = (sceneJson.objects || [])
    .filter(o => o.type === 'sphere')
    .map(o => ({
      cx: o.center[0], cy: o.center[1], cz: o.center[2],
      r: o.radius,
      mat: o.material,
    }));

  // Camera
  const cam = sceneJson.camera;
  const toVec = a => ({x:a[0],y:a[1],z:a[2]});
  const vadd = (a,b) => ({x:a.x+b.x,y:a.y+b.y,z:a.z+b.z});
  const vsub = (a,b) => ({x:a.x-b.x,y:a.y-b.y,z:a.z-b.z});
  const vmul = (a,t) => ({x:a.x*t,y:a.y*t,z:a.z*t});
  const vdot = (a,b) => a.x*b.x+a.y*b.y+a.z*b.z;
  const vlen = v => Math.sqrt(vdot(v,v));
  const vnorm = v => vmul(v, 1/vlen(v));
  const vcross = (a,b) => ({x:a.y*b.z-a.z*b.y,y:a.z*b.x-a.x*b.z,z:a.x*b.y-a.y*b.x});
  const vclamp = v => ({x:Math.max(0,Math.min(1,v.x)),y:Math.max(0,Math.min(1,v.y)),z:Math.max(0,Math.min(1,v.z))});

  const lf = toVec(cam.look_from), la = toVec(cam.look_at);
  const vup = toVec(cam.vup || [0,1,0]);
  const vfov = cam.vfov || 40;
  const asp = cam.aspect || (W/H);
  const theta = vfov * Math.PI / 180;
  const h_ = Math.tan(theta/2);
  const vh = 2*h_, vw = asp*vh;
  const w_ = vnorm(vsub(lf, la));
  const u_ = vnorm(vcross(vup, w_));
  const v_ = vcross(w_, u_);
  const horiz = vmul(u_, vw);
  const vert  = vmul(v_, vh);
  const ll = vsub(vsub(vsub(lf, vmul(horiz, 0.5)), vmul(vert, 0.5)), w_);

  function getRay(s, t) {
    const dir = vnorm(vadd(vadd(ll, vmul(horiz, s)), vsub(vmul(vert, t), lf)));
    return {o: lf, d: dir};
  }

  function hitSphere(ray, sp, tmin, tmax) {
    const oc = vsub(ray.o, {x:sp.cx,y:sp.cy,z:sp.cz});
    const a = vdot(ray.d, ray.d);
    const hb = vdot(oc, ray.d);
    const c = vdot(oc,oc) - sp.r*sp.r;
    const disc = hb*hb - a*c;
    if (disc < 0) return null;
    const sq = Math.sqrt(disc);
    let root = (-hb - sq)/a;
    if (root < tmin || root > tmax) root = (-hb+sq)/a;
    if (root < tmin || root > tmax) return null;
    const p = vadd(ray.o, vmul(ray.d, root));
    const n = vnorm(vsub(p, {x:sp.cx,y:sp.cy,z:sp.cz}));
    return {t: root, p, n, mat: sp.mat};
  }

  function traceOnce(ray, depth) {
    if (depth > 4) return {x:0,y:0,z:0};
    let best = null, bestT = 1e9;
    for (const sp of spheres) {
      const h = hitSphere(ray, sp, 0.001, bestT);
      if (h) { best = h; bestT = h.t; }
    }
    if (!best) {
      // sky
      const t = 0.5*(vnorm(ray.d).y + 1);
      return vadd(vmul({x:1,y:1,z:1}, 1-t), vmul({x:0.5,y:0.7,z:1.0}, t));
    }
    const mat = best.mat;
    if (mat.type === 'metal') {
      const ref = vnorm(vsub(ray.d, vmul(best.n, 2*vdot(ray.d, best.n))));
      const c2 = traceOnce({o: best.p, d: ref}, depth+1);
      const al = toVec(mat.albedo);
      return {x: al.x*c2.x, y: al.y*c2.y, z: al.z*c2.z};
    }
    if (mat.type === 'emissive') {
      const c2 = toVec(mat.colour);
      const s = mat.strength || 1;
      return vmul(c2, s);
    }
    // Lambertian / Phong
    const al = mat.type === 'phong' ? toVec(mat.diffuse) : toVec(mat.albedo || [0.5,0.5,0.5]);
    // random hemisphere direction
    let rn;
    do { rn = {x:Math.random()*2-1,y:Math.random()*2-1,z:Math.random()*2-1}; }
    while (vdot(rn,rn) >= 1);
    rn = vnorm(rn);
    if (vdot(rn, best.n) < 0) rn = vmul(rn,-1);
    const c2 = traceOnce({o: best.p, d: rn}, depth+1);
    return {x: al.x*c2.x, y: al.y*c2.y, z: al.z*c2.z};
  }

  function acesFilm(x) {
    return Math.max(0, Math.min(1, (x*(2.51*x+0.03))/(x*(2.43*x+0.59)+0.14)));
  }

  let pixIdx = 0;
  for (let row = H-1; row >= 0; row--) {
    for (let col = 0; col < W; col++) {
      let acc = {x:0,y:0,z:0};
      for (let s=0; s<spp; s++) {
        const u = (col + Math.random()) / W;
        const v = (row + Math.random()) / H;
        acc = vadd(acc, traceOnce(getRay(u, v), 0));
      }
      acc = vmul(acc, 1/spp);
      const r = Math.floor(Math.pow(acesFilm(acc.x), 1/2.2) * 255.999);
      const g = Math.floor(Math.pow(acesFilm(acc.y), 1/2.2) * 255.999);
      const b = Math.floor(Math.pow(acesFilm(acc.z), 1/2.2) * 255.999);
      const py = H - 1 - row;
      const i = (py * W + col) * 4;
      img.data[i]   = r;
      img.data[i+1] = g;
      img.data[i+2] = b;
      img.data[i+3] = 255;
    }
  }
  ctx.putImageData(img, 0, 0);
  const elapsed = ((performance.now() - t0)/1000).toFixed(2);
  setStatus(`JS preview done in ${elapsed}s — sphere primitives only`, 'ok');
}

function setStatus(msg, cls='') {
  const el = document.getElementById('status-msg');
  el.textContent = msg;
  el.className = cls || '';
}

// Auto-load default scene on page open
window.addEventListener('load', loadScene);
</script>
</body>
</html>
"""


def launch_editor(port=8765):
    """Start a local HTTP server with the scene editor and render endpoint."""
    script_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    scenes_dir = os.path.join(script_dir, 'scenes')

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass  # suppress default access log

        def send_json(self, data, status=200):
            body = json.dumps(data).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', len(body))
            self.end_headers()
            self.wfile.write(body)

        def send_text(self, text, status=200, ct='text/plain'):
            body = text.encode()
            self.send_response(status)
            self.send_header('Content-Type', ct)
            self.send_header('Content-Length', len(body))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path

            if path == '/' or path == '/index.html':
                self.send_text(_build_html(), ct='text/html')
                return

            if path.startswith('/scene/'):
                name = path[7:].strip('/')
                scene_file = os.path.join(scenes_dir, name + '.json')
                if not os.path.exists(scene_file):
                    self.send_text(f'Scene not found: {name}', 404)
                    return
                with open(scene_file) as f:
                    self.send_text(f.read(), ct='application/json')
                return

            self.send_text('Not found', 404)

        def do_POST(self):
            if self.path == '/render':
                length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(length)
                try:
                    scene_dict = json.loads(body)
                    png_b64, w, h, rps = _render_scene(scene_dict)
                    self.send_json({
                        'png_b64': png_b64,
                        'width': w, 'height': h,
                        'rays_per_sec': rps,
                    })
                except Exception as e:
                    tb = traceback.format_exc()
                    self.send_text(f'{e}\n\n{tb}', 500)
                return
            self.send_text('Not found', 404)

    server = http.server.HTTPServer(('localhost', port), Handler)
    print(f"\nLumina Scene Editor running at  http://localhost:{port}/")
    print("Open the URL in your browser. Press Ctrl+C to quit.\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nEditor stopped.")


def _render_scene(scene_dict):
    """Render a scene dict in-process, return (png_b64, w, h, rays_per_sec)."""
    import tempfile
    import time
    from lumina.core.scene_loader import load_scene
    from lumina.core.pathtracer import render_path, render_whitted_full
    from lumina.core.png import encode_png, tonemap as do_tonemap

    camera, world, lights, settings = load_scene(scene_dict)
    W, H = settings['width'], settings['height']
    S, md = settings['samples'], settings['max_depth']
    mode = settings['mode']
    sky_raw = settings.get('sky')
    tm = settings.get('tonemap', 'aces')

    t0 = time.perf_counter()
    if mode == 'whitted':
        pixels = render_whitted_full(
            world=world, camera=camera, lights=lights,
            sky_colour=sky_raw, width=W, height=H, samples=S, max_depth=md,
        )
    else:
        from lumina.core.vec3 import Vec3
        def sky_fn(ray):
            if sky_raw is not None: return sky_raw
            t2 = 0.5 * (ray.direction.unit().y + 1.0)
            return Vec3(1, 1, 1) * (1 - t2) + Vec3(0.5, 0.7, 1.0) * t2
        pixels = render_path(
            world=world, camera=camera, sky_fn=sky_fn,
            width=W, height=H, samples_per_pixel=S, max_depth=md,
        )
    elapsed = time.perf_counter() - t0

    rgb = do_tonemap(pixels, method=tm)
    png_bytes = encode_png(W, H, rgb)
    png_b64 = base64.b64encode(png_bytes).decode()
    rps = f"{W * H * S / elapsed:,.0f}" if elapsed > 0 else "?"
    return png_b64, W, H, rps
