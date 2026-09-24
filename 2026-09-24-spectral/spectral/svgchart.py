"""A tiny, dependency-free SVG line-chart generator for the visualizer.

No charting library is used anywhere in this project (matching the rest
of the codec: pure Python, self-contained output); this hand-rolls just
enough of a line chart -- axes, gridlines, ticks, labelled series, a
legend -- to plot the rate-distortion curves.
"""
import html

MARGIN_L, MARGIN_R, MARGIN_T, MARGIN_B = 56, 20, 20, 40
COLORS = ["#7dd3fc", "#fca5a5", "#86efac"]  # sky / rose / green, colorblind-distinct enough at 3 series


def _fmt(v):
    if abs(v - round(v)) < 1e-9:
        return str(int(round(v)))
    return f"{v:.1f}"


def line_chart(series, width=480, height=280, x_label="", y_label="", y_log=False, title=""):
    """`series`: list of (name, [(x, y), ...]) tuples. Returns an <svg> string."""
    all_x = [x for _, pts in series for x, _ in pts]
    all_y = [y for _, pts in series for _, y in pts]
    x_min, x_max = min(all_x), max(all_x)
    if y_log:
        y_min, y_max = min(all_y), max(all_y)
        y_min = max(y_min, 1e-6)

        def y_to_frac(y):
            import math
            return (math.log(max(y, y_min)) - math.log(y_min)) / (math.log(y_max) - math.log(y_min) or 1)
    else:
        y_min, y_max = min(all_y), max(all_y)
        pad = (y_max - y_min) * 0.08 or 1
        y_min, y_max = y_min - pad, y_max + pad

        def y_to_frac(y):
            return (y - y_min) / (y_max - y_min or 1)

    plot_w = width - MARGIN_L - MARGIN_R
    plot_h = height - MARGIN_T - MARGIN_B

    def x_px(x):
        return MARGIN_L + (x - x_min) / (x_max - x_min or 1) * plot_w

    def y_px(y):
        return MARGIN_T + (1 - y_to_frac(y)) * plot_h

    parts = [f'<svg viewBox="0 0 {width} {height}" class="rd-chart" role="img" aria-label="{html.escape(title)}">']
    parts.append(f'<rect x="0" y="0" width="{width}" height="{height}" fill="var(--chart-bg)" rx="8"/>')

    # gridlines + y ticks
    n_ticks = 5
    for i in range(n_ticks + 1):
        frac = i / n_ticks
        gy = MARGIN_T + frac * plot_h
        parts.append(f'<line x1="{MARGIN_L}" y1="{gy:.1f}" x2="{width - MARGIN_R}" y2="{gy:.1f}" class="grid"/>')
        if y_log:
            import math
            yv = math.exp(math.log(y_min) + (1 - frac) * (math.log(y_max) - math.log(y_min)))
        else:
            yv = y_min + (1 - frac) * (y_max - y_min)
        parts.append(f'<text x="{MARGIN_L - 8}" y="{gy + 4:.1f}" class="tick" text-anchor="end">{_fmt(yv)}</text>')

    xs_sorted = sorted(set(all_x))
    for x in xs_sorted:
        gx = x_px(x)
        parts.append(f'<text x="{gx:.1f}" y="{height - MARGIN_B + 18}" class="tick" text-anchor="middle">{_fmt(x)}</text>')

    # axis labels
    parts.append(f'<text x="{MARGIN_L + plot_w / 2:.1f}" y="{height - 6}" class="axis-label" text-anchor="middle">{html.escape(x_label)}</text>')
    parts.append(
        f'<text x="14" y="{MARGIN_T + plot_h / 2:.1f}" class="axis-label" text-anchor="middle" '
        f'transform="rotate(-90 14 {MARGIN_T + plot_h / 2:.1f})">{html.escape(y_label)}</text>'
    )

    for i, (name, pts) in enumerate(series):
        color = COLORS[i % len(COLORS)]
        pts_sorted = sorted(pts)
        path = " ".join(f"{'M' if j == 0 else 'L'}{x_px(x):.1f},{y_px(y):.1f}" for j, (x, y) in enumerate(pts_sorted))
        parts.append(f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2.5" class="series-line"/>')
        for x, y in pts_sorted:
            parts.append(f'<circle cx="{x_px(x):.1f}" cy="{y_px(y):.1f}" r="3.5" fill="{color}"><title>{_fmt(x)}: {_fmt(y)}</title></circle>')

    legend_x = MARGIN_L + 6
    for i, (name, _pts) in enumerate(series):
        color = COLORS[i % len(COLORS)]
        ly = MARGIN_T + 14 + i * 16
        parts.append(f'<circle cx="{legend_x}" cy="{ly}" r="4" fill="{color}"/>')
        parts.append(f'<text x="{legend_x + 10}" y="{ly + 4}" class="legend">{html.escape(name)}</text>')

    parts.append("</svg>")
    return "".join(parts)
