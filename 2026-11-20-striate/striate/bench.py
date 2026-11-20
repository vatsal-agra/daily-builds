"""Robustness benchmark: decode success rate versus blur / noise / ink gain / module size."""
import random

from . import encode, scan_image, raster

SYMBOLOGIES = ["code128", "ean13", "ean8", "code39", "itf"]
SWEEPS = {
    # name: (label, unit, levels, fixed-params-override-key)
    "blur":   ("Gaussian blur", "σ px", [0.0, 0.6, 0.9, 1.2, 1.5, 1.8]),
    "noise":  ("Sensor noise", "σ grey levels", [0, 15, 30, 45, 60, 80]),
    "gain":   ("Ink gain (bar growth per edge)", "px", [0.0, 0.3, 0.6, 0.9, 1.2, 1.5]),
    "module": ("Module width", "px", [1.2, 1.6, 2.0, 2.5, 3.0, 4.0]),
}
BASE = dict(module=3.0, gain=0.15, blur=0.5, noise=6)


def payload(kind, rnd):
    dig = lambda n: "".join(rnd.choice("0123456789") for _ in range(n))
    if kind == "code128":
        return "".join(rnd.choice("ABCDEFGHJKLMNPQRSTUVWXYZ0123456789") for _ in range(10))
    if kind == "ean13":
        return "5" + dig(11)                  # leading digit != 0 so it stays EAN-13 (0 would read as UPC-A)
    if kind == "ean8":
        return dig(7)
    if kind == "code39":
        return "".join(rnd.choice("ABCDEFGHJKLMNPQRSTUVWXYZ0123456789") for _ in range(8))
    return dig(10)                            # itf


def degrade(barcode, module, gain, blur, noise, seed):
    img = raster.render_subpixel(barcode, module=module, height=48, gain=gain)
    if blur > 0:
        img = raster.blur(img, blur)
    if noise > 0:
        img = raster.noise(img, noise, seed=seed)
    return img


def trial(kind, params, seed):
    rnd = random.Random(seed)
    b = encode(kind, payload(kind, rnd))
    img = degrade(b, params["module"] + rnd.uniform(-0.1, 0.1) * params["module"], params["gain"], params["blur"], params["noise"], seed)
    got = scan_image(img, max_lines=24, rotate=False)
    ok = any(d.symbology == b.symbology and d.text == b.text for d in got)
    wrong = any(not (d.symbology == b.symbology and d.text == b.text) for d in got)
    return ok, wrong


def run(sweeps=None, n=6, symbologies=None, seed0=1000):
    """-> {sweep: {symbology: [(rate_ok, rate_wrong), ...]}} aligned with SWEEPS[sweep][2]."""
    sweeps = sweeps or list(SWEEPS)
    symbologies = symbologies or SYMBOLOGIES
    out = {}
    for sw in sweeps:
        if sw not in SWEEPS:
            raise ValueError(f"unknown sweep {sw!r}; choose from {', '.join(SWEEPS)}")
        out[sw] = {}
        for kind in symbologies:
            row = []
            for li, level in enumerate(SWEEPS[sw][2]):
                params = dict(BASE); params[sw] = level
                oks = wrongs = 0
                for t in range(n):
                    ok, wrong = trial(kind, params, seed0 + 97 * li + t)
                    oks += ok; wrongs += wrong
                row.append((oks / n, wrongs / n))
            out[sw][kind] = row
    return out


def format_table(results):
    lines = []
    for sw, per in results.items():
        label, unit, levels = SWEEPS[sw]
        lines.append(f"\n{label} ({unit})")
        lines.append("  " + "symbology".ljust(10) + "".join(f"{l:>8}" for l in levels) + "   wrong")
        for kind, row in per.items():
            wrong = sum(w for _, w in row)
            lines.append("  " + kind.ljust(10) + "".join(f"{int(round(r * 100)):>7}%" for r, _ in row) + f"   {wrong:.0%}".replace("0%", "0"))
    return "\n".join(lines)


PALETTE = {"code128": "#2a6fdb", "ean13": "#e07a1f", "ean8": "#1f9d6b", "code39": "#a23fc4", "itf": "#cf3b5b"}


def chart_svg(sw, per, w=420, h=250):
    """Small inline SVG line chart (success % vs severity)."""
    label, unit, levels = SWEEPS[sw]
    L, R, T, B = 44, 12, 28, 42
    pw, ph = w - L - R, h - T - B
    x = lambda i: L + pw * i / (len(levels) - 1)
    y = lambda v: T + ph * (1 - v)
    g = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" role="img" aria-label="{label}: decode success rate by symbology">']
    g.append(f'<text x="{L}" y="16" class="ct">{label}</text>')
    for v in (0, .25, .5, .75, 1):
        g.append(f'<line x1="{L}" x2="{w - R}" y1="{y(v):.1f}" y2="{y(v):.1f}" class="grid"/>'
                 f'<text x="{L - 6}" y="{y(v) + 4:.1f}" text-anchor="end" class="tick">{int(v * 100)}%</text>')
    for i, l in enumerate(levels):
        g.append(f'<text x="{x(i):.1f}" y="{T + ph + 16}" text-anchor="middle" class="tick">{l:g}</text>')
    g.append(f'<text x="{L + pw / 2}" y="{h - 6}" text-anchor="middle" class="tick">{unit}</text>')
    for kind, row in per.items():
        pts = " ".join(f"{x(i):.1f},{y(r):.1f}" for i, (r, _) in enumerate(row))
        c = PALETTE.get(kind, "#555")
        g.append(f'<polyline points="{pts}" fill="none" stroke="{c}" stroke-width="2.2" stroke-linejoin="round"/>')
        for i, (r, _) in enumerate(row):
            g.append(f'<circle cx="{x(i):.1f}" cy="{y(r):.1f}" r="3" fill="{c}"><title>{kind} @ {levels[i]:g}: {int(r * 100)}%</title></circle>')
    g.append("</svg>")
    return "".join(g)
