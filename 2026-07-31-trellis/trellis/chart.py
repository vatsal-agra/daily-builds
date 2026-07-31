"""A small from-scratch SVG bar/line chart renderer over a cell range --
no charting library, just direct SVG string construction. If the range is
exactly two columns wide, the first column is used as category labels and
the second as the plotted values; a single-column range is plotted against
its row position."""

from .addr import parse_addr
from .errors import TrellisError
from .functions import is_number, to_display_str

WIDTH, HEIGHT = 640, 360
PAD_L, PAD_R, PAD_T, PAD_B = 56, 20, 24, 48


def _parse_range(range_text):
    parts = range_text.strip().split(":")
    if len(parts) != 2:
        raise ValueError(f"chart range must be 'A1:B10'-style, got {range_text!r}")
    try:
        r1, c1 = parse_addr(parts[0])
        r2, c2 = parse_addr(parts[1])
    except ValueError as e:
        raise ValueError(str(e))
    return min(r1, r2), min(c1, c2), max(r1, r2), max(c1, c2)


def _cell_value(sheet, r, c):
    cell = sheet.get(r, c)
    if cell is None:
        return None
    v = cell.value
    return None if isinstance(v, TrellisError) else v


def _extract_series(workbook, sheet_name, range_text):
    if sheet_name not in workbook.sheets:
        raise ValueError(f"no such sheet: {sheet_name!r}")
    sheet = workbook.sheets[sheet_name]
    r1, c1, r2, c2 = _parse_range(range_text)

    labels, values = [], []
    if c2 - c1 == 1:
        for r in range(r1, r2 + 1):
            labels.append(to_display_str(_cell_value(sheet, r, c1)))
            v = _cell_value(sheet, r, c2)
            values.append(v if is_number(v) else 0.0)
    else:
        col = c1
        for i, r in enumerate(range(r1, r2 + 1)):
            labels.append(str(i + 1))
            v = _cell_value(sheet, r, col)
            values.append(v if is_number(v) else 0.0)
    if not values:
        raise ValueError("range contains no rows to chart")
    return labels, values


def render_chart_svg(workbook, sheet_name, range_text, kind="bar"):
    labels, values = _extract_series(workbook, sheet_name, range_text)
    lo, hi = min(0, min(values)), max(values) if values else 1
    if hi == lo:
        hi = lo + 1

    plot_w = WIDTH - PAD_L - PAD_R
    plot_h = HEIGHT - PAD_T - PAD_B

    def x_for(i):
        n = len(values)
        return PAD_L + (i + 0.5) * (plot_w / n)

    def y_for(v):
        return PAD_T + plot_h - (v - lo) / (hi - lo) * plot_h

    # This SVG is always embedded via <img src="...">, which renders it in
    # its own isolated context -- `currentColor` and CSS custom properties
    # from the host page (e.g. --text, --border used everywhere else in
    # web/index.html for light/dark theming) do NOT reach in here. The
    # first version of this chart used `fill="currentColor"` and
    # `var(--chart-bg,#fff)` expecting host-page inheritance; in dark mode
    # that resolved to the SVG's own black-on-transparent default instead,
    # making axis labels nearly unreadable against the panel's dark
    # background. Fixed by giving the chart its own explicit, always-legible
    # palette instead of trying to inherit one it structurally can't reach.
    BG, TEXT, GRID, AXIS, BAR = "#ffffff", "#1c2130", "#d9dce3", "#6b7280", "#4f6bff"

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" '
        f'viewBox="0 0 {WIDTH} {HEIGHT}" font-family="system-ui,sans-serif" font-size="11">',
        f'<rect x="0" y="0" width="{WIDTH}" height="{HEIGHT}" fill="{BG}" rx="10"/>',
    ]

    # gridlines + y-axis ticks
    ticks = 5
    for t in range(ticks + 1):
        val = lo + (hi - lo) * t / ticks
        y = y_for(val)
        parts.append(f'<line x1="{PAD_L}" y1="{y:.1f}" x2="{WIDTH - PAD_R}" y2="{y:.1f}" '
                      f'stroke="{GRID}" stroke-width="1"/>')
        parts.append(f'<text x="{PAD_L - 8}" y="{y + 3:.1f}" text-anchor="end" fill="{AXIS}">'
                      f'{val:.3g}</text>')

    zero_y = y_for(0)
    parts.append(f'<line x1="{PAD_L}" y1="{zero_y:.1f}" x2="{WIDTH - PAD_R}" y2="{zero_y:.1f}" '
                  f'stroke="{TEXT}" stroke-width="1.2"/>')

    if kind == "line":
        pts = " ".join(f"{x_for(i):.1f},{y_for(v):.1f}" for i, v in enumerate(values))
        parts.append(f'<polyline points="{pts}" fill="none" stroke="{BAR}" stroke-width="2.5"/>')
        for i, v in enumerate(values):
            parts.append(f'<circle cx="{x_for(i):.1f}" cy="{y_for(v):.1f}" r="3.2" fill="{BAR}"/>')
    else:
        n = len(values)
        bar_w = max(4.0, (plot_w / n) * 0.6)
        for i, v in enumerate(values):
            x = x_for(i) - bar_w / 2
            y0, y1 = sorted((y_for(0), y_for(v)))
            parts.append(f'<rect x="{x:.1f}" y="{y0:.1f}" width="{bar_w:.1f}" '
                          f'height="{max(0.5, y1 - y0):.1f}" fill="{BAR}" rx="2"/>')

    for i, label in enumerate(labels):
        parts.append(f'<text x="{x_for(i):.1f}" y="{HEIGHT - PAD_B + 16}" text-anchor="middle" '
                      f'fill="{TEXT}">{_xml_escape(label)[:12]}</text>')

    parts.append("</svg>")
    return "\n".join(parts)


def _xml_escape(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;"))
