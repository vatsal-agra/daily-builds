"""Stretch feature: a quality-ladder artifact gallery. Every test image is
rendered at a descending run of quality settings (100 down to 1) so the
classic JPEG artifact progression — blocking, ringing near edges, chroma
bleed on saturated color boundaries — is visible directly, annotated with
the actual byte size and compression ratio at each step."""

import base64

from . import encoder, decoder, metrics, png
from .image import TEST_IMAGES

LADDER = [100, 90, 75, 60, 45, 30, 20, 12, 6, 1]


def _data_uri(image):
    b64 = base64.b64encode(png.encode_png(image)).decode("ascii")
    return f"data:image/png;base64,{b64}"


def build_gallery(output_path, size=160, ladder=None):
    ladder = ladder or LADDER
    raw_bytes = size * size * 3
    rows = []
    for name, gen in TEST_IMAGES.items():
        img = gen(size, size)
        cells = []
        for q in ladder:
            data, _ = encoder.encode(img, quality=q)
            recon = decoder.decode(data)
            cells.append({
                "quality": q,
                "uri": _data_uri(recon),
                "bytes": len(data),
                "ratio": raw_bytes / len(data),
                "psnr": metrics.psnr(img, recon),
            })
        rows.append({"name": name, "cells": cells})

    html = _render(rows, size)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    return output_path


def _render(rows, size):
    row_html = []
    for row in rows:
        cell_html = []
        for c in row["cells"]:
            psnr_str = "∞" if c["psnr"] == float("inf") else f'{c["psnr"]:.1f}'
            cell_html.append(f"""
            <figure>
              <img src="{c['uri']}" width="{size}" height="{size}" alt="{row['name']} at quality {c['quality']}">
              <figcaption>
                <div class="q">Q{c['quality']}</div>
                <div class="b">{c['bytes']:,} B</div>
                <div class="r">{c['ratio']:.1f}&times; &middot; {psnr_str} dB</div>
              </figcaption>
            </figure>""")
        row_html.append(f"""
        <section class="filmstrip">
          <h2>{row['name']}</h2>
          <div class="strip">{''.join(cell_html)}</div>
        </section>""")

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Vignette — quality ladder gallery</title>
<style>
  :root {{
    color-scheme: light dark;
    --bg: #0f1216; --panel: #1a1f27; --text: #e8ecf1; --muted: #93a1b3; --accent: #5fb4ff;
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
  .sub {{ color: var(--muted); max-width: 760px; margin-bottom: 32px; line-height: 1.5; }}
  .filmstrip {{ margin-bottom: 36px; }}
  .filmstrip h2 {{ text-transform: capitalize; font-size: 1.1rem; margin-bottom: 10px; }}
  .strip {{ display: flex; gap: 10px; overflow-x: auto; padding-bottom: 10px; }}
  figure {{ margin: 0; flex: 0 0 auto; background: var(--panel); border-radius: 10px;
            padding: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.2); }}
  figure img {{ display: block; border-radius: 6px; image-rendering: pixelated; }}
  figcaption {{ text-align: center; margin-top: 6px; font-size: 0.78rem; }}
  figcaption .q {{ color: var(--accent); font-weight: 700; }}
  figcaption .b {{ color: var(--text); }}
  figcaption .r {{ color: var(--muted); }}
</style>
</head>
<body>
<h1>Vignette — quality ladder gallery</h1>
<div class="sub">
  Every test image compressed by Vignette's own encoder at a descending run
  of quality settings, then reconstructed by its own decoder — the
  classic JPEG rate/distortion tradeoff, made visible: blocking artifacts
  emerge in flat regions first, then ringing appears near sharp edges, then
  color-plane bleed shows up around saturated boundaries as chroma
  subsampling and heavy quantization dominate.
</div>
{''.join(row_html)}
</body>
</html>
"""
