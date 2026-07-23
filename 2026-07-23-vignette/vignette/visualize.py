"""Generates a single self-contained interactive HTML report: a quality
slider per test image (swapping between pre-rendered reconstructions with
live size/PSNR/SSIM readouts), a zoom panel showing blocking artifacts at
low quality, and a DCT coefficient magnitude heatmap for one block."""

import base64
import json
import math

from . import color, dct, encoder, decoder, metrics, png
from .image import TEST_IMAGES

QUALITIES = [95, 85, 70, 50, 30, 15, 5]


def _data_uri(image):
    b64 = base64.b64encode(png.encode_png(image)).decode("ascii")
    return f"data:image/png;base64,{b64}"


def _nearest_upscale(image, factor):
    w, h = image.width * factor, image.height * factor
    px = [(0, 0, 0)] * (w * h)
    for y in range(h):
        sy = y // factor
        for x in range(w):
            sx = x // factor
            px[y * w + x] = image.get(sx, sy)
    from .image import Image
    return Image(w, h, px)


def _dct_heatmap_svg(image, cell=28):
    # First 8x8 luma block of the image (level-shifted), forward-DCT'd.
    block = [[0.0] * 8 for _ in range(8)]
    for r in range(8):
        for c in range(8):
            rr, gg, bb = image.get(c, r)
            y, _, _ = color.rgb_to_ycbcr(rr, gg, bb)
            block[r][c] = y - 128.0
    coeffs = dct.dct_2d(block)
    mags = [[abs(coeffs[r][c]) for c in range(8)] for r in range(8)]
    flat = [v for row in mags for v in row]
    peak = max(flat) if max(flat) > 0 else 1.0

    svg = [f'<svg width="{8*cell}" height="{8*cell}" xmlns="http://www.w3.org/2000/svg">']
    for r in range(8):
        for c in range(8):
            v = mags[r][c]
            # log-scaled intensity so the DC term doesn't wash out the rest
            t = math.log1p(v) / math.log1p(peak) if peak > 0 else 0
            hue = 220 - int(220 * t)  # blue (low) -> red (high)
            svg.append(
                f'<rect x="{c*cell}" y="{r*cell}" width="{cell}" height="{cell}" '
                f'fill="hsl({hue},80%,50%)" stroke="#111" stroke-width="1"/>'
                f'<text x="{c*cell+cell/2}" y="{r*cell+cell/2+4}" '
                f'font-size="9" text-anchor="middle" fill="#fff" '
                f'font-family="monospace">{v:.0f}</text>'
            )
    svg.append("</svg>")
    return "".join(svg)


def build_report(output_path, size=192, qualities=None):
    qualities = qualities or QUALITIES
    sections = []
    dct_block_svg = None

    for name, gen in TEST_IMAGES.items():
        img = gen(size, size)
        if dct_block_svg is None:
            dct_block_svg = _dct_heatmap_svg(img)

        original_uri = _data_uri(img)
        variants = []
        for q in qualities:
            data, _ = encoder.encode(img, quality=q)
            recon = decoder.decode(data)
            variants.append({
                "quality": q,
                "uri": _data_uri(recon),
                "bytes": len(data),
                "psnr": metrics.psnr(img, recon),
                "ssim": metrics.ssim(img, recon),
            })

        # Zoom panel: crop near the image center, 4x nearest-neighbor
        # upscale, original vs lowest-quality reconstruction.
        cx, cy = size // 2 - 16, size // 2 - 16
        crop_orig = img.crop(cx, cy, 32, 32)
        lowest = decoder.decode(encoder.encode(img, quality=qualities[-1])[0])
        crop_low = lowest.crop(cx, cy, 32, 32)
        zoom_orig_uri = _data_uri(_nearest_upscale(crop_orig, 6))
        zoom_low_uri = _data_uri(_nearest_upscale(crop_low, 6))

        sections.append({
            "name": name,
            "original": original_uri,
            "variants": variants,
            "zoom_orig": zoom_orig_uri,
            "zoom_low": zoom_low_uri,
            "raw_bytes": size * size * 3,
        })

    html = _render_html(sections, qualities, dct_block_svg)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    return output_path


def _render_html(sections, qualities, dct_block_svg):
    data_json = json.dumps(sections)
    n_levels = len(qualities)
    max_idx = n_levels - 1

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Vignette — JPEG codec report</title>
<style>
  :root {{
    color-scheme: light dark;
    --bg: #0f1216; --panel: #1a1f27; --text: #e8ecf1; --muted: #93a1b3;
    --accent: #5fb4ff;
  }}
  @media (prefers-color-scheme: light) {{
    :root {{ --bg: #f4f6f9; --panel: #ffffff; --text: #1a2027; --muted: #5a6472; --accent: #1d6fd6; }}
  }}
  * {{ box-sizing: border-box; }}
  body {{
    background: var(--bg); color: var(--text); font-family: -apple-system, "Segoe UI", Roboto, sans-serif;
    margin: 0; padding: 32px 20px 80px;
  }}
  h1 {{ font-size: 1.6rem; margin-bottom: 4px; }}
  .sub {{ color: var(--muted); margin-bottom: 32px; }}
  .card {{
    background: var(--panel); border-radius: 14px; padding: 20px 24px; margin-bottom: 28px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.2); max-width: 980px;
  }}
  .card h2 {{ margin-top: 0; text-transform: capitalize; font-size: 1.2rem; }}
  .row {{ display: flex; gap: 24px; flex-wrap: wrap; align-items: flex-start; }}
  .imgwrap {{
    background: repeating-conic-gradient(#8884 0% 25%, #0000 0% 50%) 50% / 16px 16px;
    border-radius: 8px; overflow: hidden; line-height: 0;
  }}
  img {{ display: block; image-rendering: pixelated; max-width: 100%; }}
  .stats {{ min-width: 220px; }}
  .stats div {{ margin: 4px 0; font-variant-numeric: tabular-nums; }}
  .stats .big {{ font-size: 1.4rem; color: var(--accent); font-weight: 600; }}
  input[type=range] {{ width: 260px; accent-color: var(--accent); }}
  .zoom-row {{ display: flex; gap: 16px; margin-top: 16px; align-items: flex-start; flex-wrap: wrap; }}
  .zoom-row figure {{ margin: 0; width: 192px; }}
  .zoom-row .imgwrap {{ width: 192px; height: 192px; }}
  .zoom-row figcaption {{ color: var(--muted); font-size: 0.8rem; margin-top: 6px; text-align: center; }}
  .heat {{ display: flex; gap: 20px; align-items: center; flex-wrap: wrap; }}
  code {{ color: var(--accent); }}
</style>
</head>
<body>
<h1>Vignette — baseline JPEG codec, interactive report</h1>
<div class="sub">
  Every image below was compressed by Vignette's own from-scratch encoder
  into real, spec-valid baseline JFIF bytes, then reconstructed by its own
  from-scratch decoder. Drag each slider to see the quality/size/PSNR/SSIM
  tradeoff live.
</div>

<div class="card">
  <h2>DCT coefficient magnitudes</h2>
  <div class="heat">
    {dct_block_svg}
    <div class="stats">
      <div>Forward 2D DCT of the top-left 8&times;8 luma block of the first
      test image (level-shifted to [-128,127]).</div>
      <div style="margin-top:8px">Top-left cell is the <b>DC</b> coefficient
      (average brightness of the block); cells further right/down are
      higher horizontal/vertical spatial frequencies. Quantization divides
      each of these by a table entry that grows with frequency — this is
      the step that discards the coefficients the eye is least sensitive
      to.</div>
    </div>
  </div>
</div>

<div id="sections"></div>

<script>
const DATA = {data_json};
const QUALITIES = {json.dumps(qualities)};
const MAXIDX = {max_idx};

const root = document.getElementById('sections');
DATA.forEach((sec, si) => {{
  const card = document.createElement('div');
  card.className = 'card';
  card.innerHTML = `
    <h2>${{sec.name}}</h2>
    <div class="row">
      <div class="imgwrap"><img id="img-${{si}}" src="${{sec.variants[0].uri}}" width="${{192}}" height="${{192}}"></div>
      <div class="stats">
        <div>Quality: <span class="big" id="q-${{si}}">${{sec.variants[0].quality}}</span></div>
        <input type="range" id="slider-${{si}}" min="0" max="${{MAXIDX}}" value="0" step="1">
        <div>Size: <b id="bytes-${{si}}"></b> (raw RGB: ${{sec.raw_bytes.toLocaleString()}} B)</div>
        <div>Compression ratio: <b id="ratio-${{si}}"></b></div>
        <div>PSNR: <b id="psnr-${{si}}"></b> dB</div>
        <div>SSIM: <b id="ssim-${{si}}"></b></div>
      </div>
    </div>
    <div class="zoom-row">
      <figure><div class="imgwrap"><img src="${{sec.zoom_orig}}"></div><figcaption>original (6&times; zoom)</figcaption></figure>
      <figure><div class="imgwrap"><img src="${{sec.zoom_low}}"></div><figcaption>quality ${{QUALITIES[QUALITIES.length-1]}} (6&times; zoom) — note 8&times;8 blocking</figcaption></figure>
    </div>
  `;
  root.appendChild(card);

  const img = card.querySelector(`#img-${{si}}`);
  const slider = card.querySelector(`#slider-${{si}}`);
  const q = card.querySelector(`#q-${{si}}`);
  const bytesEl = card.querySelector(`#bytes-${{si}}`);
  const ratioEl = card.querySelector(`#ratio-${{si}}`);
  const psnrEl = card.querySelector(`#psnr-${{si}}`);
  const ssimEl = card.querySelector(`#ssim-${{si}}`);

  function update(idx) {{
    const v = sec.variants[idx];
    img.src = v.uri;
    q.textContent = v.quality;
    bytesEl.textContent = v.bytes.toLocaleString() + ' B';
    ratioEl.textContent = (sec.raw_bytes / v.bytes).toFixed(2) + '×';
    psnrEl.textContent = v.psnr > 1e6 ? '∞' : v.psnr.toFixed(2);
    ssimEl.textContent = v.ssim.toFixed(4);
  }}
  slider.addEventListener('input', () => update(+slider.value));
  update(0);
}});
</script>
</body>
</html>
"""
