"""Self-contained, dependency-free HTML report generator.

Every chart is hand-rolled inline SVG (a handful of `<polyline>`s over a
computed coordinate transform) — no charting library, no build step, no
external JS. The page is theme-aware (light/dark via `prefers-color-scheme`
plus an explicit toggle) the same way this repo's other HTML visualizers
are, and every number shown is read straight out of an `ExperimentResult` —
nothing here is a stand-in for real measurements.
"""
from __future__ import annotations

import html
from typing import List, Sequence, Tuple

from .experiment import ExperimentResult

PALETTE = ["#4C78A8", "#F58518", "#54A24B", "#E45756", "#B279A2", "#9D755D"]


def _downsample(points: Sequence[Tuple[float, float]], max_points: int = 400) -> List[Tuple[float, float]]:
    if len(points) <= max_points:
        return list(points)
    step = len(points) / max_points
    out = []
    i = 0.0
    while int(i) < len(points):
        out.append(points[int(i)])
        i += step
    return out


def _svg_line_chart(
    series: List[Tuple[str, str, Sequence[Tuple[float, float]]]],
    width: int = 640, height: int = 220, x_label: str = "time (s)", y_label: str = "",
    title: str = "",
) -> str:
    """series: list of (label, color, [(x, y), ...])"""
    pad_l, pad_r, pad_t, pad_b = 56, 16, 28, 32
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b

    all_pts = [p for _, _, pts in series for p in pts]
    if not all_pts:
        xs, ys = [0.0, 1.0], [0.0, 1.0]
    else:
        xs = [p[0] for p in all_pts]
        ys = [p[1] for p in all_pts]
    x_min, x_max = min(xs), max(xs)
    y_min, y_max = 0.0, max(ys) if ys else 1.0
    if x_max <= x_min:
        x_max = x_min + 1.0
    if y_max <= y_min:
        y_max = y_min + 1.0

    def sx(x: float) -> float:
        return pad_l + (x - x_min) / (x_max - x_min) * plot_w

    def sy(y: float) -> float:
        return pad_t + plot_h - (y - y_min) / (y_max - y_min) * plot_h

    parts = [f'<svg viewBox="0 0 {width} {height}" class="chart" role="img" aria-label="{html.escape(title)}">']
    parts.append(f'<rect x="0" y="0" width="{width}" height="{height}" class="chart-bg"/>')

    # gridlines + y-axis ticks
    for i in range(5):
        gy = pad_t + plot_h * i / 4
        val = y_max - (y_max - y_min) * i / 4
        parts.append(f'<line x1="{pad_l}" y1="{gy:.1f}" x2="{width - pad_r}" y2="{gy:.1f}" class="grid"/>')
        parts.append(f'<text x="{pad_l - 6}" y="{gy + 4:.1f}" class="tick" text-anchor="end">{_fmt(val)}</text>')
    for i in range(5):
        gx = pad_l + plot_w * i / 4
        val = x_min + (x_max - x_min) * i / 4
        parts.append(f'<text x="{gx:.1f}" y="{height - pad_b + 16}" class="tick" text-anchor="middle">{_fmt(val)}</text>')

    parts.append(f'<line x1="{pad_l}" y1="{pad_t}" x2="{pad_l}" y2="{pad_t + plot_h}" class="axis"/>')
    parts.append(f'<line x1="{pad_l}" y1="{pad_t + plot_h}" x2="{width - pad_r}" y2="{pad_t + plot_h}" class="axis"/>')

    for label, color, pts in series:
        pts = _downsample(pts)
        if not pts:
            continue
        pts_str = " ".join(f"{sx(x):.1f},{sy(y):.1f}" for x, y in pts)
        parts.append(f'<polyline points="{pts_str}" fill="none" stroke="{color}" stroke-width="1.6"/>')

    parts.append(f'<text x="{width/2:.1f}" y="{height - 4}" class="axis-label" text-anchor="middle">{html.escape(x_label)}</text>')
    parts.append(f'<text x="14" y="{pad_t - 8}" class="axis-label">{html.escape(y_label)}</text>')
    if title:
        parts.append(f'<text x="{pad_l}" y="16" class="chart-title">{html.escape(title)}</text>')
    parts.append("</svg>")
    return "".join(parts)


def _fmt(v: float) -> str:
    if abs(v) >= 1_000_000:
        return f"{v/1_000_000:.1f}M"
    if abs(v) >= 1_000:
        return f"{v/1_000:.1f}K"
    return f"{v:.0f}"


def _legend(series: List[Tuple[str, str]]) -> str:
    items = "".join(
        f'<span class="legend-item"><span class="swatch" style="background:{c}"></span>{html.escape(l)}</span>'
        for l, c in series
    )
    return f'<div class="legend">{items}</div>'


def _experiment_section(label: str, result: ExperimentResult) -> str:
    flow_colors = [(f.name, PALETTE[i % len(PALETTE)]) for i, f in enumerate(result.flows)]

    cwnd_series = [(f.name, c, f.cwnd_series) for (f, (_, c)) in zip(result.flows, flow_colors)]
    rtt_series = [(f.name, c, [(t, r * 1000) for t, r in f.rtt_series if r == r])  # drop NaN
                  for (f, (_, c)) in zip(result.flows, flow_colors)]
    queue_series = [("queue bytes", "#888", result.queue_samples)]

    row_html = []
    for f in result.flows:
        comp = f"{f.completion_time:.2f}s" if (f.completed and f.completion_time is not None) else "cap hit"
        verified = "✓" if f.verified_correct else "✗ MISMATCH"
        row_html.append(
            f"<tr><td>{html.escape(f.name)}</td><td>{html.escape(f.cc_name)}</td>"
            f"<td>{f.data_bytes:,}</td><td>{comp}</td>"
            f"<td>{f.throughput_Bps:,.0f}</td>"
            f"<td>{f.timeouts}</td><td>{f.fast_retransmits}</td>"
            f"<td class='{'ok' if f.verified_correct else 'bad'}'>{verified}</td></tr>"
        )
    rows = "".join(row_html)

    fairness_line = ""
    if result.fairness_index is not None:
        fairness_line = f"<p><b>Jain's fairness index:</b> {result.fairness_index:.4f} (1.0 = perfectly fair)</p>"

    return f"""
<section class="exp">
  <h2>{html.escape(label)}</h2>
  <p class="desc">{html.escape(result.description)}</p>
  <p class="meta">bottleneck: {result.bandwidth_Bps:,.0f} B/s, buffer {result.buffer_bytes:,} bytes,
     duration {result.duration_s:.2f}s, drops: {result.dropped_overflow} overflow / {result.dropped_random} random</p>
  {fairness_line}
  <table>
    <thead><tr><th>flow</th><th>algo</th><th>bytes</th><th>completed</th>
    <th>throughput B/s</th><th>timeouts</th><th>fast retx</th><th>verified</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
  <div class="charts">
    <div class="chart-box">
      {_svg_line_chart(cwnd_series, y_label="cwnd (bytes)", title="Congestion window over time")}
      {_legend(flow_colors)}
    </div>
    <div class="chart-box">
      {_svg_line_chart(rtt_series, y_label="SRTT (ms)", title="Smoothed RTT over time")}
      {_legend(flow_colors)}
    </div>
    <div class="chart-box">
      {_svg_line_chart(queue_series, y_label="bytes", title="Shared bottleneck queue occupancy")}
    </div>
  </div>
</section>
"""


def build_html(named_results: List[Tuple[str, ExperimentResult]]) -> str:
    nav = "".join(f'<a href="#{label}">{html.escape(label)}</a>' for label, _ in named_results)
    sections = "".join(_experiment_section(label, r).replace('<section class="exp">',
                        f'<section class="exp" id="{label}">') for label, r in named_results)

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Throttle — TCP / congestion-control experiment report</title>
<style>
:root {{
  --bg: #f7f7f5; --panel: #ffffff; --text: #1b1f23; --muted: #5b6270;
  --border: #e2e2e0; --accent: #4C78A8; --ok: #1a7f37; --bad: #cf222e;
  --grid: #ececeb; --axis: #999;
}}
@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{
    --bg: #14161a; --panel: #1c1f24; --text: #e6e6e6; --muted: #9aa1ab;
    --border: #2c2f36; --accent: #7aa8d8; --ok: #56d364; --bad: #ff7b72;
    --grid: #262a31; --axis: #666;
  }}
}}
:root[data-theme="dark"] {{
  --bg: #14161a; --panel: #1c1f24; --text: #e6e6e6; --muted: #9aa1ab;
  --border: #2c2f36; --accent: #7aa8d8; --ok: #56d364; --bad: #ff7b72;
  --grid: #262a31; --axis: #666;
}}
* {{ box-sizing: border-box; }}
body {{ background: var(--bg); color: var(--text); font-family: -apple-system, BlinkMacSystemFont,
  "Segoe UI", Helvetica, Arial, sans-serif; margin: 0; padding: 0 0 4rem; }}
header {{ padding: 2rem 2rem 1rem; border-bottom: 1px solid var(--border); }}
header h1 {{ margin: 0 0 .25rem; font-size: 1.5rem; }}
header p {{ color: var(--muted); margin: 0; }}
nav {{ padding: .75rem 2rem; display: flex; gap: 1rem; flex-wrap: wrap; border-bottom: 1px solid var(--border); }}
nav a {{ color: var(--accent); text-decoration: none; font-size: .9rem; }}
nav a:hover {{ text-decoration: underline; }}
main {{ max-width: 1080px; margin: 0 auto; padding: 0 2rem; }}
section.exp {{ padding: 2rem 0; border-bottom: 1px solid var(--border); }}
section.exp h2 {{ margin: 0 0 .5rem; font-size: 1.15rem; }}
.desc {{ color: var(--text); max-width: 760px; }}
.meta {{ color: var(--muted); font-size: .85rem; }}
table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; font-size: .85rem; }}
th, td {{ text-align: left; padding: .4rem .6rem; border-bottom: 1px solid var(--border); }}
th {{ color: var(--muted); font-weight: 600; }}
td.ok {{ color: var(--ok); }}
td.bad {{ color: var(--bad); font-weight: 700; }}
.charts {{ display: flex; gap: 1.25rem; flex-wrap: wrap; }}
.chart-box {{ flex: 1 1 300px; min-width: 280px; background: var(--panel); border: 1px solid var(--border);
  border-radius: 8px; padding: .5rem; }}
.chart {{ width: 100%; height: auto; }}
.chart-bg {{ fill: var(--panel); }}
.grid {{ stroke: var(--grid); stroke-width: 1; }}
.axis {{ stroke: var(--axis); stroke-width: 1; }}
.tick {{ font-size: 9px; fill: var(--muted); }}
.axis-label {{ font-size: 10px; fill: var(--muted); }}
.chart-title {{ font-size: 11px; fill: var(--text); font-weight: 600; }}
.legend {{ display: flex; gap: .75rem; flex-wrap: wrap; padding: .35rem .25rem 0; font-size: .75rem; color: var(--muted); }}
.legend-item {{ display: flex; align-items: center; gap: .3rem; }}
.swatch {{ width: 9px; height: 9px; border-radius: 2px; display: inline-block; }}
</style>
</head>
<body>
<header>
  <h1>Throttle — TCP / congestion-control experiment report</h1>
  <p>Packet-level discrete-event network + a real TCP implementation + pluggable Reno/Tahoe/CUBIC congestion control. Every chart below is real, measured simulator output.</p>
</header>
<nav>{nav}</nav>
<main>
{sections}
</main>
</body>
</html>"""
