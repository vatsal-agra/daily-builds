"""Paint: turn a positioned LayoutBox tree into SVG.

Painting follows the CSS2.1 painting order for the (non-positioned,
non-floated) subset Folio implements: background, then border, then
content (text), for each box in tree order -- background/borders of an
element under its descendants' backgrounds/borders, and everything under
its own text (CSS2.1 Appendix E, stacking levels 3/4/6 for our scope).
"""

import html as _html_escape_module

from .values import color_to_css


def _esc(s):
    return _html_escape_module.escape(s, quote=True)


def paint_svg(root_box, width, height, background="#ffffff"):
    parts = []
    # Folio's line-breaker assumes a fixed per-character advance width (see
    # fontmetrics.py) rather than rasterizing real glyphs -- painting with a
    # monospace font keeps what's *drawn* consistent with what was
    # *measured*, instead of silently mismatching a proportional font.
    parts.append(
        '<svg xmlns="http://www.w3.org/2000/svg" width="%g" height="%g" '
        'viewBox="0 0 %g %g" font-family="\'Courier New\', monospace">'
        % (width, height, width, height)
    )
    parts.append('<rect x="0" y="0" width="%g" height="%g" fill="%s"/>' % (width, height, background))
    _paint_box(root_box, parts)
    parts.append("</svg>")
    return "\n".join(parts)


def _paint_box(box, parts):
    x, y, w, h = box.rect()
    style = box.style

    bg = None
    if not box.is_anonymous and style is not None:
        bg = style.get("background-color")
    if bg and bg[3] > 0 and w > 0 and h > 0:
        parts.append(
            '<rect x="%g" y="%g" width="%g" height="%g" fill="%s"/>'
            % (x, y, w, h, color_to_css(bg))
        )

    if not box.is_anonymous and style is not None:
        _paint_borders(box, parts)

    if box.mode == "inline":
        _paint_lines(box, parts)

    for child in box.block_children:
        _paint_box(child, parts)


def _paint_borders(box, parts):
    style = box.style
    x, y, w, h = box.rect()
    sides = [
        ("top", box.border_top, x, y, w, box.border_top),
        ("bottom", box.border_bottom, x, y + h - box.border_bottom, w, box.border_bottom),
        ("left", box.border_left, x, y, box.border_left, h),
        ("right", box.border_right, x + w - box.border_right, y, box.border_right, h),
    ]
    for side, width_px, rx, ry, rw, rh in sides:
        if width_px <= 0:
            continue
        bstyle = style.get("border-%s-style" % side, "none")
        if bstyle == "none":
            continue
        color = style.get("border-%s-color" % side) or (0, 0, 0, 255)
        parts.append(
            '<rect x="%g" y="%g" width="%g" height="%g" fill="%s"/>'
            % (rx, ry, max(rw, 0), max(rh, 0), color_to_css(color))
        )


def _paint_lines(box, parts):
    for line in box.lines:
        for frag_x, text, fstyle, fwidth in line.fragments:
            if text == "":
                continue
            color = fstyle.get("color", (0, 0, 0, 255))
            font_size = fstyle.get("font-size", 16.0)
            weight = fstyle.get("font-weight", "normal")
            style_kw = fstyle.get("font-style", "normal")
            baseline_y = line.y + font_size * 0.9
            attrs = 'font-size="%g" fill="%s"' % (font_size, color_to_css(color))
            if weight == "bold":
                attrs += ' font-weight="bold"'
            if style_kw == "italic":
                attrs += ' font-style="italic"'
            parts.append(
                '<text x="%g" y="%g" %s>%s</text>'
                % (frag_x, baseline_y, attrs, _esc(text))
            )


def page_height(root_box):
    return root_box.border_box_bottom + root_box.margin_bottom
