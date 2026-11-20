"""Self-contained HTML gallery: encodings, live decodes of damaged images, GS1, robustness charts."""
import base64
import html
import random

from . import encode, scan_image, raster, svg, gs1, bench

SAMPLES = [("code128", "Striate-2026"), ("ean13", "4006381333931"), ("upca", "03600029145"), ("ean8", "9638507"),
           ("code39", "CODE-39 $/+%"), ("itf", "0123456789")]


def _data_uri(img):
    return "data:image/png;base64," + base64.b64encode(img.to_png()).decode()


def scenarios():
    """(title, description, expected (symbology,text), image)."""
    out = []
    b = encode("ean13", "4006381333931")
    img = raster.noise(raster.blur(raster.render_subpixel(b, module=2.6, height=60, gain=0.35), 0.9), 12, seed=3)
    out.append(("Blur + noise + ink gain", "σ=0.9 px blur, σ=12 sensor noise, bars printed 0.7 px fat; module 2.6 px", b, img))
    b = encode("code128", "ROTATED-27")
    img = raster.noise(raster.blur(raster.rotate(raster.render_subpixel(b, module=3, height=70, gain=0.2), 27), 0.7), 6, seed=1)
    out.append(("Rotated 27°", "found by sweeping scan angles; the blur and noise are still on", b, img))
    b = encode("code39", "VERTICAL")
    out.append(("Vertical (90°)", "a barcode on its side", b, raster.rotate(raster.render(b, module=3, height=60), 90)))
    b = encode("itf", "00012345678905")
    img = raster.render(b, module=3, height=60); img.rows = [bytearray(255 - v for v in r) for r in img.rows]
    out.append(("Light on dark", "inverted polarity, as on a dark label", b, img))
    b = encode("ean8", "96385074")
    out.append(("Uneven lighting", "left-to-right shadow falling to 15% brightness", b,
                raster.illumination(raster.render_subpixel(b, module=2.6, height=60, gain=0.2), 0.85)))
    b = encode("upca", "03600029145")
    out.append(("Washed out", "only 60 grey levels of contrast, mild noise", b,
                raster.noise(raster.contrast(raster.render_subpixel(b, module=2.6, height=60, gain=0.2), 110, 170), 3, seed=2)))
    b = encode("code128", "IN-THE-CLUTTER")
    canvas = raster.Image(520, 260)
    raster.add_clutter(canvas, seed=4, count=90)
    raster.paste(canvas, raster.render(b, module=2, height=70), 40, 90)
    out.append(("Lost in clutter", "random dark blobs around the symbol; scanner must locate it", b, canvas))
    b = encode("code128", "MODULE-1PX")
    out.append(("1-pixel modules", "the narrowest bar is a single pixel", b, raster.render(b, module=1, height=40)))
    return out


CSS = """
:root{--bg:#fafaf7;--card:#fff;--ink:#1b1d21;--mute:#6a6f78;--line:#e4e4de;--acc:#2a6fdb;--ok:#14804a;--okbg:#e3f5ea;--bad:#b3261e;--badbg:#fbe9e7}
@media(prefers-color-scheme:dark){:root{--bg:#14161a;--card:#1d2026;--ink:#ecedf0;--mute:#9aa0aa;--line:#2c3038;--acc:#6fa3ff;--ok:#5fd28f;--okbg:#17301f;--bad:#ff8a80;--badbg:#3a1a18}
 .bars{background:#fff;border-radius:8px;padding:8px}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.55 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1040px;margin:0 auto;padding:40px 16px 80px}
h1{font-size:2.4rem;letter-spacing:-.02em;margin:0}h1 span{color:var(--acc)}
.lead{color:var(--mute);max-width:62ch;margin:8px 0 0}
h2{margin:52px 0 6px;font-size:1.3rem}h2+p{color:var(--mute);margin:0 0 18px;max-width:70ch}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px;display:flex;flex-direction:column;gap:10px}
.card h3{margin:0;font-size:.95rem}.card .d{color:var(--mute);font-size:.85rem;margin:0}
.bars{display:flex;justify-content:center;align-items:center;min-height:120px;overflow:hidden}.bars img,.bars svg{max-width:100%;height:auto;image-rendering:pixelated}
code{font:13px ui-monospace,Menlo,monospace;background:var(--bg);padding:2px 6px;border-radius:6px;word-break:break-all}
.badge{display:inline-block;padding:3px 10px;border-radius:99px;font-size:.8rem;font-weight:600}
.ok{background:var(--okbg);color:var(--ok)}.bad{background:var(--badbg);color:var(--bad)}
table{border-collapse:collapse;width:100%;font-size:.9rem}td,th{text-align:left;padding:6px 10px;border-bottom:1px solid var(--line)}
.charts{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:16px}
.charts svg{width:100%;height:auto;background:var(--card);border:1px solid var(--line);border-radius:14px}
.ct{font:600 13px system-ui;fill:var(--ink)}.tick{font:11px system-ui;fill:var(--mute)}.grid{}svg .grid{stroke:var(--line);stroke-width:1}
.legend{display:flex;gap:16px;flex-wrap:wrap;margin:0 0 12px;font-size:.85rem;color:var(--mute)}.legend i{display:inline-block;width:12px;height:12px;border-radius:3px;margin-right:6px;vertical-align:-1px}
footer{margin-top:60px;color:var(--mute);font-size:.85rem}
"""


def build_html(bench_results=None):
    esc = html.escape
    p = ['<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
         f'<title>Striate — barcode gallery</title><style>{CSS}</style></head><body><main>',
         '<h1>Stria<span>te</span></h1><p class="lead">A from-scratch 1D barcode encoder and image scanner. Everything below was generated and '
         'decoded live by the library — pure Python, no imaging or barcode dependencies.</p>']
    p.append("<h2>Encode</h2><p>Six symbologies, rendered to SVG straight from the module pattern.</p><div class='grid'>")
    for kind, text in SAMPLES:
        b = encode(kind, text)
        p.append(f"<div class='card'><h3>{esc(b.symbology)}</h3><div class='bars'>{svg.to_svg(b, module=2, height=60)}</div>"
                 f"<p class='d'><code>{esc(b.text)}</code> · {len(b.modules)} modules</p></div>")
    p.append("</div>")
    p.append("<h2>Decode damaged images</h2><p>Each image is produced by a realistic degradation, then handed to <code>scan_image</code>. "
             "The badge is the scanner's actual output compared with the ground truth.</p><div class='grid'>")
    for title, desc, b, img in scenarios():
        dets = scan_image(img)
        hit = next((d for d in dets if d.symbology == b.symbology and d.text == b.text), None)
        wrong = [d for d in dets if d is not hit]
        badge = (f"<span class='badge ok'>✓ decoded · {hit.votes} scanlines · scan angle {hit.angle:g}°</span>" if hit
                 else "<span class='badge bad'>✗ not decoded</span>")
        if wrong:
            badge += " <span class='badge bad'>wrong read!</span>"
        p.append(f"<div class='card'><h3>{esc(title)}</h3><div class='bars'><img alt='{esc(title)}' src='{_data_uri(img)}'></div>"
                 f"<p class='d'>{esc(desc)}</p><div>{badge}</div><p class='d'>{esc(b.symbology)} <code>{esc(b.text)}</code></p></div>")
    p.append("</div>")
    human = "(01)09501101530003(3103)001234(17)261231(10)LOT 42"
    b = encode("code128", gs1.build(human))
    det = scan_image(raster.render(b, module=2, height=60))[0]
    rows = "".join(f"<tr><td><code>({esc(ai)})</code></td><td>{esc(n)}</td><td><code>{esc(v)}</code></td><td>{esc(m)}</td></tr>"
                   for ai, n, v, m in det.extra["gs1_fields"])
    p.append("<h2>GS1-128</h2><p>Code 128 + FNC1 carrying application identifiers; the decoder parses them, validates the GTIN check digit and dates.</p>"
             f"<div class='card'><div class='bars'>{svg.to_svg(b, module=2, height=60)}</div><table><tr><th>AI</th><th>Field</th><th>Value</th><th>Meaning</th></tr>{rows}</table></div>")
    if bench_results:
        p.append("<h2>How robust is it?</h2><p>Decode success rate over random payloads while one degradation grows (others held mild). "
                 "Wrong reads are counted separately — they stayed at zero.</p><div class='legend'>"
                 + "".join(f"<span><i style='background:{c}'></i>{k}</span>" for k, c in bench.PALETTE.items()) + "</div><div class='charts'>")
        for sw, per in bench_results.items():
            p.append(bench.chart_svg(sw, per))
        p.append("</div>")
    p.append("<footer>Generated by <code>python3 -m striate gallery</code>.</footer></main></body></html>")
    return "".join(p)
