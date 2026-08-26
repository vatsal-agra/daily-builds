"""Paint: walks the final LayoutBox tree and emits a real SVG document —
background rects, independently-styled 4-sided borders, and text runs
positioned per line box at their computed baseline. Inline elements
(`<span>`, `<a>`, `<b>`...) get correct per-line-fragment backgrounds and
borders: a multi-line `<span style="background:yellow">` gets one rect per
line it touches, with the left edge only on its first fragment and the
right edge only on its last (real CSS inline-box fragmentation — see
layout.py's module docstring for the one place this simplifies: fragment
padding is drawn but not reserved in the line-breaking width)."""

from .cascade import parse_color, color_to_svg
from .layout import px0, border_width, is_monospace


def _esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def resolve_color_prop(style, prop):
    raw = style.get(prop).strip()
    if raw.lower() == "currentcolor":
        raw = style.get("color")
    return parse_color(raw)


def paint_svg(root_box, viewport_width):
    total_h = 1.0
    for b in root_box.walk():
        bb = b.dims.border_box()
        total_h = max(total_h, bb.y + bb.height)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{viewport_width}" '
        f'height="{total_h:.1f}" viewBox="0 0 {viewport_width} {total_h:.1f}">',
        f'<rect x="0" y="0" width="{viewport_width}" height="{total_h:.1f}" fill="white"/>',
    ]
    _paint_box(root_box, parts)
    parts.append("</svg>")
    return "\n".join(parts)


def _paint_box(box, parts):
    if box.box_type == "block" and box.node is not None:
        _paint_block_visuals(box, parts)
    if box.box_type == "anon-inline":
        _paint_inline_content(box, parts)
    for c in box.children:
        _paint_box(c, parts)


def _rect(x, y, w, h, color_rgba, extra=""):
    if h <= 0 or w <= 0 or color_rgba[3] <= 0:
        return ""
    fill, op = color_to_svg(color_rgba)
    op_attr = f' fill-opacity="{op:.3f}"' if op < 1 else ""
    return f'<rect x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}" fill="{fill}"{op_attr}{extra}/>\n'


def _paint_block_visuals(box, parts):
    style = box.style
    bb = box.dims.border_box()
    bg = resolve_color_prop(style, "background-color")
    parts.append(_rect(bb.x, bb.y, bb.width, bb.height, bg))

    e = box.dims.border
    if e.top > 0 and style.get("border-top-style") != "none":
        parts.append(_rect(bb.x, bb.y, bb.width, e.top, resolve_color_prop(style, "border-top-color")))
    if e.bottom > 0 and style.get("border-bottom-style") != "none":
        parts.append(_rect(bb.x, bb.y + bb.height - e.bottom, bb.width, e.bottom,
                            resolve_color_prop(style, "border-bottom-color")))
    if e.left > 0 and style.get("border-left-style") != "none":
        parts.append(_rect(bb.x, bb.y + e.top, e.left, bb.height - e.top - e.bottom,
                            resolve_color_prop(style, "border-left-color")))
    if e.right > 0 and style.get("border-right-style") != "none":
        parts.append(_rect(bb.x + bb.width - e.right, bb.y + e.top, e.right, bb.height - e.top - e.bottom,
                            resolve_color_prop(style, "border-right-color")))


def _compute_fragments(anon_box):
    """dict[Element] -> ordered list of (line_index, minx, maxx, line_top,
    line_height, style) — one entry per line that element's text touches."""
    frag_map = {}
    for li, line in enumerate(anon_box.lines):
        current = {}  # owner -> [minx, maxx, style]
        for w in line.words:
            if w.text is None:
                continue  # inline-block box tokens paint themselves
            for owner in w.owners:
                if owner not in current:
                    current[owner] = [w.x, w.x + w.width, w.style]
                else:
                    current[owner][1] = w.x + w.width
        for owner, (minx, maxx, style) in current.items():
            frag_map.setdefault(owner, []).append((li, minx, maxx, line.top, line.height, style))
    return frag_map


def _paint_inline_content(anon_box, parts):
    frag_map = _compute_fragments(anon_box)
    for owner, frags in frag_map.items():
        for idx, (li, minx, maxx, top, height, style) in enumerate(frags):
            is_first = idx == 0
            is_last = idx == len(frags) - 1
            pl = px0(style.get("padding-left"), 0) if is_first else 0
            pr = px0(style.get("padding-right"), 0) if is_last else 0
            pt = px0(style.get("padding-top"), 0)
            pb = px0(style.get("padding-bottom"), 0)
            bl = border_width(style, "left") if is_first else 0
            br_ = border_width(style, "right") if is_last else 0
            bt = border_width(style, "top")
            bb_ = border_width(style, "bottom")
            rx = minx - pl - bl
            ry = top - pt - bt
            rw = (maxx - minx) + pl + pr + bl + br_
            rh = height + pt + pb + bt + bb_
            bg = resolve_color_prop(style, "background-color")
            parts.append(_rect(rx, ry, rw, rh, bg))
            if bt > 0 and style.get("border-top-style") != "none":
                parts.append(_rect(rx, ry, rw, bt, resolve_color_prop(style, "border-top-color")))
            if bb_ > 0 and style.get("border-bottom-style") != "none":
                parts.append(_rect(rx, ry + rh - bb_, rw, bb_, resolve_color_prop(style, "border-bottom-color")))
            if bl > 0 and style.get("border-left-style") != "none":
                parts.append(_rect(rx, ry, bl, rh, resolve_color_prop(style, "border-left-color")))
            if br_ > 0 and style.get("border-right-style") != "none":
                parts.append(_rect(rx + rw - br_, ry, br_, rh, resolve_color_prop(style, "border-right-color")))

    for line in anon_box.lines:
        for w in line.words:
            if w.text is None:
                continue
            baseline_y = line.top + line.baseline
            color = resolve_color_prop(w.style, "color")
            fill, op = color_to_svg(color)
            op_attr = f' fill-opacity="{op:.3f}"' if op < 1 else ""
            fs = px0(w.style.get("font-size"), 16)
            weight = "bold" if w.style.get("font-weight") == "bold" else "normal"
            fstyle = "italic" if w.style.get("font-style") == "italic" else "normal"
            family = "monospace" if is_monospace(w.style.get("font-family")) else "sans-serif"
            parts.append(
                f'<text x="{w.x:.2f}" y="{baseline_y:.2f}" font-size="{fs:.2f}" '
                f'font-family="{family}" font-weight="{weight}" font-style="{fstyle}" '
                f'fill="{fill}"{op_attr}>{_esc(w.text)}</text>\n'
            )
        for sx, ex, color in _underline_runs(line):
            fill, op = color_to_svg(color)
            uy = line.top + line.baseline + 2
            parts.append(f'<line x1="{sx:.2f}" y1="{uy:.2f}" x2="{ex:.2f}" y2="{uy:.2f}" '
                          f'stroke="{fill}" stroke-width="1"/>\n')


def _underline_runs(line):
    """Merges consecutive underlined words on a line into continuous runs
    (so the line is drawn through the inter-word gaps too, like a real
    text-decoration, not one broken segment per word)."""
    runs = []
    start = end = None
    color = None
    for w in line.words:
        if w.text is not None and w.underline:
            if start is None:
                start = w.x
                color = resolve_color_prop(w.style, "color")
            end = w.x + w.width
        else:
            if start is not None:
                runs.append((start, end, color))
                start = None
    if start is not None:
        runs.append((start, end, color))
    return runs
