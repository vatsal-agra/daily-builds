"""Generates a self-contained interactive HTML visualizer.

Every image shown is embedded as a real `data:image/jpeg;base64,...` URI
of actual Spectral-encoded bytes -- the *browser's own* JPEG decoder
renders them, the same independent-oracle proof used throughout this
project's test suite, just presented as a page instead of a test
assertion. No chart library, no build step, no external assets.
"""
import base64
import json

from . import decoder, encoder, metrics, progressive, testimages
from .svgchart import line_chart

QUALITIES_FOR_SLIDER = [5, 15, 30, 50, 70, 85, 95]
RD_QUALITIES = [5, 10, 20, 30, 40, 50, 60, 70, 80, 90, 95, 100]
SUBSAMPLINGS = ["444", "422", "420"]


def _data_uri(jpeg_bytes):
    return "data:image/jpeg;base64," + base64.b64encode(jpeg_bytes).decode("ascii")


def _progressive_scan_boundaries(data):
    """Byte offsets marking the end of each scan in a Spectral-produced
    progressive file (see viz.py module docstring / REVIEW.md: this
    assumes the specific single-SOS-per-scan, no-other-markers-between-
    scans structure this codec's own encoder always produces).
    """
    positions = []
    start = 0
    while True:
        idx = data.find(bytes([0xFF, 0xDA]), start)
        if idx == -1:
            break
        positions.append(idx)
        start = idx + 2
    eoi_idx = data.rfind(bytes([0xFF, 0xD9]))
    return positions[1:] + [eoi_idx]


def _quality_slider_data(img):
    frames = {}
    raw_size = img.width * img.height * 3
    for q in QUALITIES_FOR_SLIDER:
        data = encoder.encode(img, quality=q, subsampling="420")
        out = decoder.decode(data)
        frames[q] = {
            "uri": _data_uri(data),
            "bytes": len(data),
            "psnr": metrics.psnr(img, out),
            "ratio": raw_size / len(data),
        }
    return frames


def _rd_curve_data(img):
    series_size = []
    series_psnr = []
    for ss in SUBSAMPLINGS:
        pts_size, pts_psnr = [], []
        for q in RD_QUALITIES:
            data = encoder.encode(img, quality=q, subsampling=ss)
            out = decoder.decode(data)
            pts_size.append((q, len(data)))
            pts_psnr.append((q, metrics.psnr(img, out)))
        series_size.append((f"4:{ss[1]}:{ss[2]}", pts_size))
        series_psnr.append((f"4:{ss[1]}:{ss[2]}", pts_psnr))
    return series_size, series_psnr


def _subsampling_compare_data(img, quality=60):
    out = {}
    for ss in SUBSAMPLINGS:
        data = encoder.encode(img, quality=quality, subsampling=ss)
        dec = decoder.decode(data)
        out[ss] = {"uri": _data_uri(data), "bytes": len(data), "psnr": metrics.psnr(img, dec)}
    return out


def _progressive_reveal_data(img, quality=80):
    data = progressive.encode(img, quality=quality, subsampling="420")
    boundaries = _progressive_scan_boundaries(data)
    frames = []
    for i, b in enumerate(boundaries):
        partial = data[:b] + bytes([0xFF, 0xD9])
        out = progressive.decode(partial)
        if i == 0:
            scan_kind = "DC (coarse, Ah=0 Al=1)"
        elif i == 1:
            scan_kind = "DC (refined, Ah=1 Al=0)"
        else:
            component = ("Y", "Cb", "Cr")[(i - 2) // 2]
            band = (i - 2) % 2 + 1
            scan_kind = f"AC band {band} ({component})"
        frames.append({
            "uri": _data_uri(partial),
            "bytes": len(partial),
            "psnr": metrics.psnr(img, out),
            "label": f"scan {i + 1}/{len(boundaries)}: {scan_kind}",
        })
    baseline_data = encoder.encode(img, quality=quality, subsampling="420")
    return frames, len(baseline_data)


def build(output_path, seed=1):
    img = testimages.synthetic_photo(120, 96, seed=seed)

    slider = _quality_slider_data(img)
    rd_size, rd_psnr = _rd_curve_data(img)
    subsample = _subsampling_compare_data(img)
    prog_frames, prog_baseline_size = _progressive_reveal_data(img)

    size_chart = line_chart(rd_size, x_label="Quality", y_label="File size (bytes)", y_log=True, title="Size vs quality")
    psnr_chart = line_chart(rd_psnr, x_label="Quality", y_label="PSNR (dB)", title="PSNR vs quality")

    html_doc = _render(img, slider, size_chart, psnr_chart, subsample, prog_frames, prog_baseline_size)
    with open(output_path, "w") as f:
        f.write(html_doc)


def _render(img, slider, size_chart, psnr_chart, subsample, prog_frames, prog_baseline_size):
    slider_json = json.dumps({str(q): v for q, v in slider.items()})
    qualities_json = json.dumps(QUALITIES_FOR_SLIDER)
    prog_json = json.dumps(prog_frames)
    subsample_json = json.dumps(subsample)

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Spectral — JPEG codec visualizer</title>
<style>
{_CSS}
</style>
</head>
<body>
<div class="page">
  <header>
    <h1>Spectral</h1>
    <p class="subtitle">A from-scratch JPEG codec — every image below is real Spectral-encoded output, rendered by <em>your browser's own</em> JPEG decoder.</p>
  </header>

  <section class="card">
    <h2>1. Quality slider</h2>
    <p class="hint">Drag to see the classic JPEG rate/quality trade-off on a real encode of the same {img.width}&times;{img.height} synthetic photo, at 4:2:0 subsampling.</p>
    <div class="slider-row">
      <input type="range" id="qslider" min="0" max="{len(QUALITIES_FOR_SLIDER) - 1}" step="1" value="4">
      <div class="slider-stats" id="qstats"></div>
    </div>
    <img id="qimg" class="preview" alt="quality preview">
  </section>

  <section class="card">
    <h2>2. Rate-distortion curves</h2>
    <p class="hint">File size and quality (PSNR) vs. the quality setting, for all 3 chroma subsampling modes. More subsampling (4:2:0) trades color resolution for smaller files at every quality level.</p>
    <div class="charts">
      <div>{size_chart}</div>
      <div>{psnr_chart}</div>
    </div>
  </section>

  <section class="card">
    <h2>3. Chroma subsampling, side by side</h2>
    <p class="hint">Same quality (60), three subsampling modes. Look closely at color edges (the diagonal seams between the colored patches) — 4:2:0 blurs color detail nearby to save bits; luma (brightness) detail is unaffected in all three.</p>
    <div class="subsample-grid" id="subsample-grid"></div>
  </section>

  <section class="card">
    <h2>4. Progressive JPEG: scan-by-scan reveal</h2>
    <p class="hint">A real progressive (SOF2) encode of the same image, truncated after each successive scan and re-terminated with EOI — each frame below is itself a complete, independently valid, browser-decodable JPEG file. The DC scan alone (frame 1) is a blocky per-8&times;8-block preview; each AC spectral-selection band after it adds real detail. Final size: {prog_frames[-1]['bytes']:,} bytes across {len(prog_frames)} scans (a single-scan baseline encode at the same quality is {prog_baseline_size:,} bytes).</p>
    <div class="slider-row">
      <input type="range" id="pslider" min="0" max="{len(prog_frames) - 1}" step="1" value="{len(prog_frames) - 1}">
      <div class="slider-stats" id="pstats"></div>
    </div>
    <img id="pimg" class="preview" alt="progressive scan preview">
  </section>

  <footer>Generated by <code>spectral.viz</code> — see PLAN.md / REVIEW.md in the project repo for the full codec writeup.</footer>
</div>

<script>
const SLIDER_DATA = {slider_json};
const QUALITIES = {qualities_json};
const PROG_FRAMES = {prog_json};
const SUBSAMPLE = {subsample_json};

function fmtBytes(n) {{ return n.toLocaleString() + ' B'; }}
function fmtPsnr(p) {{ return isFinite(p) ? p.toFixed(1) + ' dB' : 'lossless'; }}

const qslider = document.getElementById('qslider');
const qimg = document.getElementById('qimg');
const qstats = document.getElementById('qstats');
function updateQuality() {{
  const q = QUALITIES[+qslider.value];
  const d = SLIDER_DATA[String(q)];
  qimg.src = d.uri;
  qstats.innerHTML = `<b>quality ${{q}}</b> &middot; ${{fmtBytes(d.bytes)}} &middot; ${{d.ratio.toFixed(1)}}&times; smaller than raw &middot; ${{fmtPsnr(d.psnr)}}`;
}}
qslider.addEventListener('input', updateQuality);
updateQuality();

const pslider = document.getElementById('pslider');
const pimg = document.getElementById('pimg');
const pstats = document.getElementById('pstats');
function updateProgressive() {{
  const f = PROG_FRAMES[+pslider.value];
  pimg.src = f.uri;
  pstats.innerHTML = `<b>${{f.label}}</b> &middot; ${{fmtBytes(f.bytes)}} so far &middot; ${{fmtPsnr(f.psnr)}}`;
}}
pslider.addEventListener('input', updateProgressive);
updateProgressive();

const grid = document.getElementById('subsample-grid');
for (const ss of ['444', '422', '420']) {{
  const d = SUBSAMPLE[ss];
  const cell = document.createElement('div');
  cell.className = 'subsample-cell';
  cell.innerHTML = `<img src="${{d.uri}}" alt="4:${{ss[1]}}:${{ss[2]}}"><div class="subsample-label"><b>4:${{ss[1]}}:${{ss[2]}}</b><br>${{fmtBytes(d.bytes)}} &middot; ${{fmtPsnr(d.psnr)}}</div>`;
  grid.appendChild(cell);
}}
</script>
</body>
</html>
"""


_CSS = """
:root {
  --bg: #0b1020;
  --card-bg: #131a2e;
  --chart-bg: #0e1526;
  --text: #e6ebf5;
  --muted: #93a0bd;
  --accent: #7dd3fc;
  --border: #223052;
  color-scheme: dark;
}
@media (prefers-color-scheme: light) {
  :root:not([data-theme="dark"]) {
    --bg: #f4f6fb;
    --card-bg: #ffffff;
    --chart-bg: #f8fafc;
    --text: #10182b;
    --muted: #4a5578;
    --accent: #0369a1;
    --border: #dfe6f5;
    color-scheme: light;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  line-height: 1.5;
}
.page { max-width: 920px; margin: 0 auto; padding: 24px 16px 60px; }
header { margin-bottom: 24px; }
h1 { font-size: 2rem; margin: 0 0 6px; letter-spacing: -0.02em; }
.subtitle { color: var(--muted); margin: 0; max-width: 60ch; }
.card {
  background: var(--card-bg);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 20px;
  margin-bottom: 20px;
}
h2 { margin: 0 0 8px; font-size: 1.15rem; }
.hint { color: var(--muted); font-size: 0.92rem; margin: 0 0 14px; max-width: 72ch; }
.slider-row { display: flex; align-items: center; gap: 14px; margin-bottom: 12px; flex-wrap: wrap; }
input[type=range] { flex: 1 1 220px; accent-color: var(--accent); }
.slider-stats { font-size: 0.92rem; color: var(--muted); white-space: nowrap; }
.slider-stats b { color: var(--text); }
.preview {
  width: 100%;
  max-width: 480px;
  border-radius: 10px;
  border: 1px solid var(--border);
  image-rendering: pixelated;
  display: block;
}
.charts { display: flex; gap: 16px; flex-wrap: wrap; }
.charts > div { flex: 1 1 380px; min-width: 0; }
.rd-chart { width: 100%; height: auto; }
.grid { stroke: var(--border); stroke-width: 1; }
.tick { fill: var(--muted); font-size: 10px; }
.axis-label { fill: var(--muted); font-size: 11px; }
.legend { fill: var(--text); font-size: 11px; }
.series-line { opacity: 0.95; }
.subsample-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 14px; }
.subsample-cell img {
  width: 100%;
  border-radius: 10px;
  border: 1px solid var(--border);
  image-rendering: pixelated;
  display: block;
}
.subsample-label { font-size: 0.85rem; color: var(--muted); margin-top: 6px; }
.subsample-label b { color: var(--text); }
footer { color: var(--muted); font-size: 0.85rem; text-align: center; margin-top: 30px; }
footer code { color: var(--accent); }
@media (max-width: 480px) {
  h1 { font-size: 1.6rem; }
  .card { padding: 16px; }
}
"""
