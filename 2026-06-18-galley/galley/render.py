"""Renderers: justified SVG, a full HTML document, and a monospace ASCII column.

Given a :class:`~galley.linebreak.Breaking` and the node list it was computed
from, these turn the chosen breaks into real, viewable output.  The spacing on
each line comes directly from that line's adjustment ratio: a glue of natural
width ``w``, stretch ``y`` and shrink ``z`` is set to ``w + r*y`` when ``r >= 0``
and ``w + r*z`` when ``r < 0`` (with ``r`` clamped to ``-1`` so spaces never
collapse past their shrink limit).
"""

from __future__ import annotations

import html
from typing import List, Tuple

from .linebreak import Breaking, Line, badness
from .model import build_paragraph


def _xml_escape(s: str) -> str:
    return html.escape(s, quote=True)


def adjusted_glue(width: float, stretch: float, shrink: float, ratio: float) -> float:
    """Set width of a glue under adjustment ratio ``ratio`` (clamped at -1)."""
    r = max(ratio, -1.0)
    if r >= 0:
        return width + r * stretch
    return width + r * shrink


def layout_line(items, line: Line) -> Tuple[List[Tuple[float, str]], float]:
    """Place a line's boxes at absolute x offsets.

    Returns ``(runs, end_x)`` where ``runs`` is a list of ``(x, text)`` for each
    box (and a trailing hyphen if the line ends on a flagged break), and
    ``end_x`` is the x where the line content ends.
    """
    runs: List[Tuple[float, str]] = []
    x = 0.0
    i = line.start
    # Skip leading discardable glue at the start of the line.
    while i < line.end and items[i].is_glue:
        i += 1
    while i < line.end:
        it = items[i]
        if it.is_box:
            if it.text:
                runs.append((x, it.text))
            x += it.width
        elif it.is_glue:
            x += adjusted_glue(it.width, it.stretch, it.shrink, line.ratio)
        # penalties inside the line have zero set-width (their width only
        # appears when a break is taken *at* them)
        i += 1
    # Trailing hyphen if the line was broken at a flagged penalty.
    if line.flagged and not line.forced and line.end < len(items) and items[line.end].is_penalty:
        runs.append((x, "-"))
        x += items[line.end].width
    return runs, x


# --------------------------------------------------------------------------- #
# SVG
# --------------------------------------------------------------------------- #

_HEAT = [
    (0.0, "#1a9850"), (15.0, "#66bd63"), (40.0, "#a6d96a"),
    (80.0, "#fee08b"), (150.0, "#fdae61"), (400.0, "#f46d43"),
    (1e11, "#d73027"),
]


def _heat_color(bad: float) -> str:
    for thresh, color in _HEAT:
        if bad <= thresh:
            return color
    return "#d73027"


def render_svg(
    items,
    breaking: Breaking,
    font,
    measure: float,
    *,
    leading: float = None,
    margin: float = 16.0,
    heat: bool = False,
    show_measure: bool = True,
    background: str = "#fbfaf7",
    title: str = None,
) -> str:
    """Render a broken paragraph as a standalone, self-contained SVG string."""
    if leading is None:
        leading = font.size * 1.32
    n_lines = len(breaking.lines)
    title_h = 0.0 if not title else font.size * 1.8 + 8
    width = measure + 2 * margin
    height = title_h + 2 * margin + n_lines * leading
    baseline0 = margin + title_h + font.size

    parts: List[str] = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.1f}" '
        f'height="{height:.1f}" viewBox="0 0 {width:.1f} {height:.1f}" '
        f'font-family="{font.css}">'
    )
    parts.append(f'<rect width="{width:.1f}" height="{height:.1f}" fill="{background}"/>')
    if title:
        parts.append(
            f'<text x="{margin:.1f}" y="{margin + font.size*1.2:.1f}" '
            f'font-size="{font.size*1.1:.1f}" fill="#444" '
            f'font-family="ui-sans-serif,system-ui,sans-serif" '
            f'font-weight="600">{_xml_escape(title)}</text>'
        )
    if show_measure:
        # Faint right margin rule so over/underfull is visible.
        rx = margin + measure
        parts.append(
            f'<line x1="{rx:.1f}" y1="{margin + title_h:.1f}" x2="{rx:.1f}" '
            f'y2="{height - margin:.1f}" stroke="#d8d2c4" stroke-width="1"/>'
        )
        parts.append(
            f'<line x1="{margin:.1f}" y1="{margin + title_h:.1f}" x2="{margin:.1f}" '
            f'y2="{height - margin:.1f}" stroke="#d8d2c4" stroke-width="1"/>'
        )

    for li, line in enumerate(breaking.lines):
        baseline = baseline0 + li * leading
        if heat:
            color = _heat_color(line.badness)
            y0 = baseline - font.size
            parts.append(
                f'<rect x="{margin:.1f}" y="{y0:.1f}" width="{measure:.1f}" '
                f'height="{leading:.1f}" fill="{color}" opacity="0.18"/>'
            )
        runs, _ = layout_line(items, line)
        for x, text in runs:
            parts.append(
                f'<text x="{margin + x:.2f}" y="{baseline:.2f}" '
                f'font-size="{font.size:.1f}" fill="#1a1a1a" '
                f'xml:space="preserve">{_xml_escape(text)}</text>'
            )
    parts.append("</svg>")
    return "".join(parts)


# --------------------------------------------------------------------------- #
# HTML document
# --------------------------------------------------------------------------- #

_HTML_SHELL = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  :root {{ color-scheme: light; }}
  body {{
    margin: 0; padding: 2.5rem 1.5rem 4rem;
    background: #11100e; color: #e9e6df;
    font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
    line-height: 1.5;
  }}
  .wrap {{ max-width: 1100px; margin: 0 auto; }}
  h1 {{ font-weight: 700; letter-spacing: -0.02em; font-size: 1.9rem; margin: 0 0 .25rem; }}
  h1 .accent {{ color: #f0b429; }}
  .sub {{ color: #9c968a; margin: 0 0 2rem; font-size: .98rem; }}
  .cards {{ display: grid; gap: 1.5rem; grid-template-columns: repeat(auto-fit, minmax(330px, 1fr)); }}
  .card {{
    background: #1c1a17; border: 1px solid #2c2a25; border-radius: 14px;
    padding: 1.1rem 1.1rem 1.3rem; box-shadow: 0 6px 24px rgba(0,0,0,.28);
  }}
  .card h2 {{ font-size: 1.05rem; margin: 0 0 .15rem; }}
  .card .meta {{ color: #9c968a; font-size: .82rem; margin: 0 0 .9rem; font-variant-numeric: tabular-nums; }}
  .card svg {{ width: 100%; height: auto; border-radius: 8px; display: block; }}
  .stats {{ display: flex; gap: 1.2rem; flex-wrap: wrap; margin-top: .9rem; font-size: .82rem; }}
  .stat b {{ display: block; font-size: 1.15rem; color: #f0b429; font-variant-numeric: tabular-nums; }}
  .stat span {{ color: #9c968a; }}
  .legend {{ display: flex; gap: .6rem; flex-wrap: wrap; margin: 1.4rem 0 0; font-size: .78rem; color: #9c968a; align-items: center; }}
  .swatch {{ width: 13px; height: 13px; border-radius: 3px; display: inline-block; vertical-align: -2px; margin-right: 3px; }}
  footer {{ margin-top: 2.6rem; color: #6f6a60; font-size: .8rem; }}
  code {{ background: #2a2722; padding: .1rem .35rem; border-radius: 4px; }}
</style>
</head>
<body>
<div class="wrap">
<h1>{heading}</h1>
<p class="sub">{subtitle}</p>
{body}
{legend}
<footer>{footer}</footer>
</div>
</body>
</html>
"""


def _stat_block(stats: List[Tuple[str, str]]) -> str:
    cells = "".join(
        f'<div class="stat"><b>{_xml_escape(v)}</b><span>{_xml_escape(k)}</span></div>'
        for k, v in stats
    )
    return f'<div class="stats">{cells}</div>'


def render_card(title: str, meta: str, svg: str, stats: List[Tuple[str, str]]) -> str:
    return (
        f'<div class="card"><h2>{_xml_escape(title)}</h2>'
        f'<p class="meta">{_xml_escape(meta)}</p>{svg}'
        f'{_stat_block(stats)}</div>'
    )


def render_html_document(heading: str, subtitle: str, cards: List[str],
                         *, title: str = "Galley", legend: bool = True,
                         footer: str = "") -> str:
    legend_html = ""
    if legend:
        sw = "".join(
            f'<span><span class="swatch" style="background:{c}"></span>'
            f'{"≤"+str(int(t)) if t < 1e10 else "overfull"}</span>'
            for t, c in _HEAT
        )
        legend_html = (
            '<div class="legend"><span>line badness:</span>' + sw + "</div>"
        )
    return _HTML_SHELL.format(
        title=_xml_escape(title), heading=heading, subtitle=_xml_escape(subtitle),
        body="".join(cards), legend=legend_html, footer=footer,
    )


# --------------------------------------------------------------------------- #
# ASCII column
# --------------------------------------------------------------------------- #

def render_ascii(items, breaking: Breaking, *, justify: bool = True) -> List[str]:
    """Render to a monospace text column.

    Assumes the breaking was computed from a monospace paragraph whose box
    widths are character counts and whose glue natural width is 1 (see
    :func:`ascii_paragraph`).  Justification distributes the surplus columns as
    extra spaces across the inter-word gaps.
    """
    out: List[str] = []
    n_lines = len(breaking.lines)
    for li, line in enumerate(breaking.lines):
        is_last = (li == n_lines - 1)
        # Collect the boxes and gap positions on the line.
        words: List[str] = []
        i = line.start
        while i < line.end and items[i].is_glue:
            i += 1
        cur = ""
        gap_after: List[bool] = []
        word_chars = 0
        while i < line.end:
            it = items[i]
            if it.is_box:
                cur += it.text
            elif it.is_glue:
                if cur:
                    words.append(cur)
                    word_chars += len(cur)
                    cur = ""
            i += 1
        if line.flagged and not line.forced and line.end < len(items) and items[line.end].is_penalty:
            cur += "-"
        if cur:
            words.append(cur)
            word_chars += len(cur)

        if not words:
            out.append("")
            continue
        target = int(round(line.target_width))
        gaps = len(words) - 1
        if not justify or is_last or gaps == 0 or line.ratio < 0:
            out.append(" ".join(words))
            continue
        # Distribute (target - word_chars) spaces across gaps, >=1 each.
        total_spaces = max(target - word_chars, gaps)
        base = total_spaces // gaps
        extra = total_spaces - base * gaps
        parts = []
        for wi, w in enumerate(words):
            parts.append(w)
            if wi < gaps:
                ng = base + (1 if wi >= gaps - extra else 0)
                parts.append(" " * ng)
        out.append("".join(parts))
    return out


def ascii_paragraph(text: str, hyphenate=None):
    """Build a node list in *character* units for ASCII rendering/breaking.

    Boxes have width = number of characters; inter-word glue has width 1 with
    one column of stretch and no shrink (monospace spaces cannot shrink).
    """
    from .model import Box, Glue, Penalty, Paragraph, INFINITY

    words = text.split()
    items: List[object] = []
    for wi, word in enumerate(words):
        if wi > 0:
            items.append(Glue(1.0, 1.0, 0.0))
        frags = [word]
        if hyphenate is not None and word.isalpha() and len(word) >= 5:
            frags = hyphenate(word)
        if len(frags) == 1:
            items.append(Box(len(word), word))
        else:
            for fi, frag in enumerate(frags):
                items.append(Box(len(frag), frag))
                if fi < len(frags) - 1:
                    items.append(Penalty(1.0, 50, flagged=True))  # hyphen = 1 col
    items.append(Penalty(0, INFINITY, flagged=False))
    items.append(Glue(0, 1e9, 0))
    items.append(Penalty(0, -INFINITY, flagged=False))
    return Paragraph(items=items, words=words)
