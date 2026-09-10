"""A flexbox subset: single-line (flex-wrap:nowrap, the real spec default)
row/column layout with flex-grow/flex-shrink/flex-basis distribution,
justify-content, and align-items:stretch/flex-start/center/flex-end.

Scope cuts (documented, not hidden): flex-wrap:wrap (multi-line) isn't
implemented; `order` isn't implemented (items lay out in DOM order); `gap`
isn't implemented; percentage flex-basis against an indefinite cross size
falls back like `auto`.
"""

from css_values import parse_length
from dom import Element
from font import measure_text
from layout import (box_edges, display_of, layout_block_box,
                     relayout_at_outer_width, visible_children)


def _main_size(b, direction):
    """Border-box size along the main axis (excludes margin)."""
    return b.width if direction == "row" else b.height


def _main_margins(b, direction):
    return (b.margin.left, b.margin.right) if direction == "row" else (b.margin.top, b.margin.bottom)


def _outer_main(b, direction):
    lead, trail = _main_margins(b, direction)
    return lead + _main_size(b, direction) + trail


def _cross_size(b, direction):
    return b.height if direction == "row" else b.width


def _cross_margins(b, direction):
    return (b.margin.top, b.margin.bottom) if direction == "row" else (b.margin.left, b.margin.right)


def _outer_cross(b, direction):
    lead, trail = _cross_margins(b, direction)
    return lead + _cross_size(b, direction) + trail


def _set_main_size(b, direction, new_main, font_size):
    if direction == "row":
        relayout_at_outer_width(b, max(new_main, 0.0), font_size)
    else:
        b.height = max(new_main, 0.0)


def _set_cross_size(b, direction, new_cross, font_size):
    if direction == "row":
        b.height = max(new_cross, 0.0)
    else:
        relayout_at_outer_width(b, max(new_cross, 0.0), font_size)


def _cross_style_is_auto(style, direction):
    prop = "height" if direction == "row" else "width"
    return style.get(prop, "auto").strip() == "auto"


def _cross_align_pos(b, direction, align, line_cross):
    """Returns the border-box offset (from the line's cross-axis start)
    for item b, accounting for its own cross-axis margins."""
    lead_margin, _trail_margin = _cross_margins(b, direction)
    outer = _outer_cross(b, direction)
    if align in ("stretch", "flex-start") or line_cross <= 0:
        return lead_margin
    if align == "center":
        return max((line_cross - outer) / 2.0, 0.0) + lead_margin
    if align == "flex-end":
        return max(line_cross - outer, 0.0) + lead_margin
    return lead_margin


def _is_leaf_text_only(el):
    return not any(isinstance(c, Element) for c in el.children)


def _layout_flex_item(el, direction, main_available, cross_available, font_size_parent):
    style = el.computed_style
    fs = parse_length(style.get("font-size", "16px"), font_size_parent).resolve(0) or font_size_parent
    main_prop = "width" if direction == "row" else "height"
    cbw = (main_available if direction == "row" else cross_available)
    cbw = cbw if cbw is not None else 0.0

    basis_len = parse_length(style.get("flex-basis", "auto"), fs)
    prop_len = parse_length(style.get(main_prop, "auto"), fs)

    override = None
    if not basis_len.auto:
        override = dict(style)
        override[main_prop] = style.get("flex-basis")
    elif prop_len.auto and direction == "row" and _is_leaf_text_only(el):
        # crude fit-content estimate: a real UA would use min/max-content
        # sizing here; we approximate with the item's own text-run width.
        text = el.text_content().strip()
        border, padding = box_edges(style, fs, cbw)
        approx_content = measure_text(text, fs) if text else 0.0
        override = dict(style)
        override[main_prop] = f"{approx_content}px"

    box = layout_block_box(el, cbw, font_size_parent, style_override=override)
    return box


def layout_flex_container(box, content_w, font_size):
    style = box.style
    direction = style.get("flex-direction", "row")
    if direction not in ("row", "column"):
        direction = "row"
    justify = style.get("justify-content", "flex-start")
    align = style.get("align-items", "stretch")
    node = box.node
    items_el = [c for c in visible_children(node) if isinstance(c, Element)] if node is not None else []

    if direction == "row":
        main_available = content_w
        cross_len = parse_length(style.get("height", "auto"), font_size)
        cross_available = None if cross_len.auto else cross_len.resolve(0)
    else:
        cross_available = content_w
        main_len = parse_length(style.get("height", "auto"), font_size)
        main_available = None if main_len.auto else main_len.resolve(0)

    items = [_layout_flex_item(el, direction, main_available, cross_available, font_size) for el in items_el]

    # Free-space distribution operates on border-box ("flex base") sizes,
    # but the space each item actually consumes along the main axis also
    # includes its own margins -- those are fixed and never grow/shrink.
    if main_available is not None and items:
        bases = [_main_size(b, direction) for b in items]
        margin_sum = sum(sum(_main_margins(b, direction)) for b in items)
        free = main_available - sum(bases) - margin_sum
        grows = [float(style_num(b.style.get("flex-grow", "0"))) for b in items]
        shrinks = [float(style_num(b.style.get("flex-shrink", "1"))) for b in items]
        if free > 0.0001 and sum(grows) > 0:
            total_grow = sum(grows)
            for i, b in enumerate(items):
                extra = free * (grows[i] / total_grow)
                _set_main_size(b, direction, bases[i] + extra, font_size)
        elif free < -0.0001:
            weights = [shrinks[i] * bases[i] for i in range(len(items))]
            weight_sum = sum(weights)
            if weight_sum > 0:
                for i, b in enumerate(items):
                    reduction = (-free) * (weights[i] / weight_sum)
                    _set_main_size(b, direction, max(bases[i] - reduction, 0.0), font_size)

    line_cross = cross_available if cross_available is not None else max(
        (_outer_cross(b, direction) for b in items), default=0.0)
    if align == "stretch":
        for b in items:
            if _cross_style_is_auto(b.style, direction):
                lead, trail = _cross_margins(b, direction)
                _set_cross_size(b, direction, max(line_cross - lead - trail, 0.0), font_size)
        line_cross = cross_available if cross_available is not None else max(
            (_outer_cross(b, direction) for b in items), default=0.0)

    total_main = sum(_outer_main(b, direction) for b in items)
    n = len(items)
    free_main = max((main_available if main_available is not None else total_main) - total_main, 0.0)
    gap = 0.0
    if justify == "center":
        pos = free_main / 2.0
    elif justify == "flex-end":
        pos = free_main
    elif justify == "space-between" and n > 1:
        pos = 0.0
        gap = free_main / (n - 1)
    elif justify == "space-around" and n > 0:
        gap = free_main / n
        pos = gap / 2.0
    else:
        pos = 0.0

    for b in items:
        lead_margin, _trail = _main_margins(b, direction)
        cross_pos = _cross_align_pos(b, direction, align, line_cross)
        if direction == "row":
            b.x, b.y = pos + lead_margin, cross_pos
        else:
            b.y, b.x = pos + lead_margin, cross_pos
        pos += _outer_main(b, direction) + gap

    box.children = items
    if direction == "row":
        box._content_h = line_cross
    else:
        box._content_h = (pos - gap) if items else 0.0


def style_num(v):
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return 0.0
