"""SVG output for barcodes, with human-readable text."""
from xml.sax.saxutils import escape


def to_svg(barcode, module=2, height=80, quiet=None, text=True, font_size=14):
    q = barcode.quiet if quiet is None else quiet
    runs = barcode.runs()
    total = len(barcode.modules)
    w = (total + 2 * q) * module
    th = (font_size + 6) if text else 0
    h = height + 2 * 6 + th
    rects, x = [], q
    for i, r in enumerate(runs):
        if i % 2 == 0:
            rects.append(f'<rect x="{x * module}" y="6" width="{r * module}" height="{height}"/>')
        x += r
    label = ""
    if text:
        t = barcode.text.replace("\xf1", "").replace("\x1d", " ")
        t = "".join(c if c.isprintable() else "?" for c in t)
        label = (f'<text x="{w / 2}" y="{6 + height + font_size + 2}" text-anchor="middle" '
                 f'font-family="monospace" font-size="{font_size}" fill="#000">{escape(t)}</text>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
            f'role="img" aria-label="{escape(barcode.symbology)} barcode {escape(barcode.text)}">'
            f'<rect width="100%" height="100%" fill="#fff"/><g fill="#000">{"".join(rects)}</g>{label}</svg>')
