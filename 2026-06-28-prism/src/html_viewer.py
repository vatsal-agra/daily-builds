"""Generate a self-contained HTML animated flipbook viewer."""
import base64


def build_html_viewer(frames_png, title="Prism — 3D Rasterizer", fps=20,
                      width=None, height=None, caption=""):
    """
    frames_png: list of PNG bytes objects (each frame).
    Returns an HTML string (self-contained, no external deps).
    """
    b64_frames = [base64.b64encode(p).decode('ascii') for p in frames_png]
    frames_js = ',\n'.join(f'"{f}"' for f in b64_frames)

    w_str = f'width="{width}"' if width else ''
    h_str = f'height="{height}"' if height else ''

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    background: #0a0a0f;
    color: #e0e0f0;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    min-height: 100vh;
    padding: 2rem;
    gap: 1.5rem;
  }}
  h1 {{
    font-size: 1.8rem;
    font-weight: 700;
    background: linear-gradient(135deg, #8080ff, #ff80c0, #80ffff);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    letter-spacing: 0.05em;
  }}
  .viewer {{
    position: relative;
    border: 1px solid #303060;
    border-radius: 12px;
    overflow: hidden;
    box-shadow: 0 0 60px rgba(100,80,255,0.3), 0 0 120px rgba(80,100,255,0.15);
  }}
  .viewer img {{
    display: block;
    image-rendering: pixelated;
    image-rendering: crisp-edges;
  }}
  .controls {{
    display: flex;
    align-items: center;
    gap: 1rem;
    flex-wrap: wrap;
    justify-content: center;
  }}
  button {{
    background: #1a1a3a;
    border: 1px solid #4040a0;
    color: #c0c0ff;
    padding: 0.5rem 1.2rem;
    border-radius: 6px;
    cursor: pointer;
    font-size: 0.95rem;
    transition: all 0.15s;
  }}
  button:hover {{ background: #2a2a5a; border-color: #6060d0; }}
  button.active {{ background: #3030a0; border-color: #8080ff; color: #fff; }}
  .progress {{
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-size: 0.85rem;
    color: #8080b0;
  }}
  input[type=range] {{
    width: 180px;
    accent-color: #6060d0;
  }}
  .info {{
    font-size: 0.8rem;
    color: #606090;
    text-align: center;
    line-height: 1.6;
  }}
  .badge {{
    display: inline-block;
    background: #1a1a3a;
    border: 1px solid #303060;
    border-radius: 4px;
    padding: 0.15rem 0.5rem;
    font-size: 0.75rem;
    color: #8080c0;
    margin: 0.1rem;
  }}
</style>
</head>
<body>
<h1>&#9670; {title}</h1>
<div class="viewer">
  <img id="frame" src="" {w_str} {h_str} alt="render frame">
</div>
<div class="controls">
  <button id="btnPlay" class="active" onclick="togglePlay()">&#9646;&#9646; Pause</button>
  <button onclick="stepFrame(-1)">&#9664; Prev</button>
  <button onclick="stepFrame(1)">Next &#9654;</button>
  <div class="progress">
    <span id="frameNum">0</span>/<span id="frameTotal">0</span>
    <input type="range" id="scrub" min="0" max="0" value="0" oninput="seekTo(+this.value)">
  </div>
  <select id="speedSel" onchange="setSpeed(+this.value)" style="background:#1a1a3a;border:1px solid #4040a0;color:#c0c0ff;padding:0.4rem;border-radius:6px">
    <option value="0.5">0.5×</option>
    <option value="1" selected>1×</option>
    <option value="2">2×</option>
    <option value="4">4×</option>
  </select>
</div>
{('<p class="info">' + caption + '</p>') if caption else ''}
<div class="info">
  <span class="badge">&#9670; Prism Software Rasterizer</span>
  <span class="badge">Pure Python</span>
  <span class="badge">{len(b64_frames)} frames @ {fps} fps</span>
</div>
<script>
const FRAMES = [
{frames_js}
];
const FPS_BASE = {fps};
let cur = 0, playing = true, speed = 1.0, interval = null;
const img = document.getElementById('frame');
const scrub = document.getElementById('scrub');
const frameNum = document.getElementById('frameNum');
const frameTotal = document.getElementById('frameTotal');
const btnPlay = document.getElementById('btnPlay');

scrub.max = FRAMES.length - 1;
frameTotal.textContent = FRAMES.length;

function showFrame(n) {{
  cur = ((n % FRAMES.length) + FRAMES.length) % FRAMES.length;
  img.src = 'data:image/png;base64,' + FRAMES[cur];
  scrub.value = cur;
  frameNum.textContent = cur + 1;
}}

function startLoop() {{
  if (interval) clearInterval(interval);
  interval = setInterval(() => {{ if (playing) showFrame(cur + 1); }},
                         Math.round(1000 / (FPS_BASE * speed)));
}}

function togglePlay() {{
  playing = !playing;
  btnPlay.textContent = playing ? '⏸ Pause' : '▶ Play';
  btnPlay.className = playing ? 'active' : '';
}}

function stepFrame(d) {{ playing = false; btnPlay.textContent = '▶ Play'; btnPlay.className=''; showFrame(cur+d); }}
function seekTo(n) {{ showFrame(n); }}
function setSpeed(s) {{ speed = s; startLoop(); }}

showFrame(0);
startLoop();
</script>
</body>
</html>
"""


def build_comparison_html(renders, title="Prism — Feature Comparison"):
    """
    renders: list of dicts with keys: label, png_bytes, caption.
    Returns HTML with a grid of static renders.
    """
    cells = []
    for r in renders:
        b64 = base64.b64encode(r['png_bytes']).decode('ascii')
        cap = r.get('caption', '')
        lbl = r.get('label', '')
        cells.append(f"""
<div class="cell">
  <img src="data:image/png;base64,{b64}" alt="{lbl}">
  <div class="label">{lbl}</div>
  {('<div class="caption">'+cap+'</div>') if cap else ''}
</div>""")

    grid = '\n'.join(cells)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{title}</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
  background: #0a0a0f; color: #e0e0f0;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  padding: 2rem;
}}
h1 {{
  font-size: 1.6rem; font-weight: 700; margin-bottom: 1.5rem;
  background: linear-gradient(135deg, #8080ff, #ff80c0, #80ffff);
  -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;
}}
.grid {{ display: flex; flex-wrap: wrap; gap: 1.5rem; justify-content: center; }}
.cell {{
  border: 1px solid #303060; border-radius: 10px; overflow: hidden;
  background: #10101e;
  box-shadow: 0 0 30px rgba(80,80,200,0.2);
}}
.cell img {{ display: block; image-rendering: pixelated; image-rendering: crisp-edges; }}
.label {{
  padding: 0.5rem 0.8rem; font-size: 0.9rem; font-weight: 600;
  color: #c0c0ff; background: #14143a;
}}
.caption {{ padding: 0 0.8rem 0.6rem; font-size: 0.75rem; color: #6060a0; }}
</style>
</head>
<body>
<h1>&#9670; {title}</h1>
<div class="grid">{grid}</div>
</body>
</html>
"""
