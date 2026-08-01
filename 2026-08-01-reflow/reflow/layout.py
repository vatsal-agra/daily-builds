"""The layout engine: turns a styled DOM tree into a positioned, sized box
tree using the real CSS box model (content/padding/border/margin), block
flow (vertical stacking with sibling margin collapsing), and inline flow
(greedy line-breaking against actual glyph widths from `font.py`).

`display: none` subtrees (including the whole <head>) are pruned here, so
neither layout nor paint ever sees them.
"""

from . import font
from .cascade import to_px

DEFAULT_FONT_SIZE = 16.0


class LayoutBox:
    __slots__ = (
        'node', 'style', 'box_type', 'children', 'x', 'y',
        'content_width', 'content_height', 'margin', 'border', 'padding',
        'background', 'border_color', 'border_style', 'fragments',
    )

    def __init__(self, node, style, box_type):
        self.node = node
        self.style = style
        self.box_type = box_type  # 'block' | 'line' | 'flex-item'
        self.children = []
        self.x = 0.0
        self.y = 0.0
        self.content_width = 0.0
        self.content_height = 0.0
        self.margin = (0.0, 0.0, 0.0, 0.0)
        self.border = (0.0, 0.0, 0.0, 0.0)
        self.padding = (0.0, 0.0, 0.0, 0.0)
        self.background = None
        self.border_color = (None, None, None, None)
        self.border_style = (None, None, None, None)
        self.fragments = []  # line boxes only: [{'x','text','color','scale'}]

    def border_box_height(self):
        pt, _pr, pb, _pl = self.padding
        bt, _br, bb, _bl = self.border
        return self.content_height + pt + pb + bt + bb

    def border_box_width(self):
        _pt, pr, _pb, pl = self.padding
        _bt, br, _bb, bl = self.border
        return self.content_width + pl + pr + bl + br

    def content_origin(self):
        bt, _br, _bb, bl = self.border
        pt, _pr, _pb, pl = self.padding
        return self.x + bl + pl, self.y + bt + pt


def _font_size_of(style):
    if style is None:
        return DEFAULT_FONT_SIZE
    return to_px(style.get('font-size'), font_size=DEFAULT_FONT_SIZE) or DEFAULT_FONT_SIZE


def _scale_for(style):
    fs = _font_size_of(style)
    return max(1, round(fs / 12.0))


def _resolve_box_model(style, containing_width):
    if style is None:
        return {
            'margin': (0.0, 0.0, 0.0, 0.0), 'border': (0.0, 0.0, 0.0, 0.0),
            'padding': (0.0, 0.0, 0.0, 0.0), 'width': containing_width,
            'height': None, 'background': None,
            'border_color': (None, None, None, None),
            'border_style': (None, None, None, None),
        }
    font_size = _font_size_of(style)

    def px(prop, base, default=0.0):
        v = to_px(style.get(prop), font_size=font_size, percent_base=base)
        return default if v is None else v

    margin = (
        px('margin-top', containing_width), px('margin-right', containing_width),
        px('margin-bottom', containing_width), px('margin-left', containing_width),
    )
    border_style = tuple(style.get(f'border-{side}-style') for side in ('top', 'right', 'bottom', 'left'))
    border = tuple(
        px(f'border-{side}-width', containing_width) if bstyle not in (None, 'none') else 0.0
        for side, bstyle in zip(('top', 'right', 'bottom', 'left'), border_style)
    )
    padding = (
        px('padding-top', containing_width), px('padding-right', containing_width),
        px('padding-bottom', containing_width), px('padding-left', containing_width),
    )
    width_val = to_px(style.get('width'), font_size=font_size, percent_base=containing_width)
    height_val = to_px(style.get('height'), font_size=font_size, percent_base=None)
    return {
        'margin': margin, 'border': border, 'padding': padding,
        'width': width_val, 'height': height_val,
        'background': style.get('background-color'),
        'border_color': tuple(style.get(f'border-{side}-color') for side in ('top', 'right', 'bottom', 'left')),
        'border_style': border_style,
    }


def _is_inline_level(node, styles):
    if node.node_type == 'text':
        return True
    if node.node_type == 'element':
        st = styles.get(node)
        return st is not None and st.get('display') == 'inline'
    return False


# Sentinel meaning "hard line break" (from a <br>), threaded through the
# token stream so it can force a line to end even mid-run.
BR = object()


def _flatten_inline(node, styles, out):
    if node.node_type == 'text':
        out.append((node.data, styles.get(node)))
        return
    if node.node_type == 'element':
        if node.name == 'br':
            out.append((BR, None))
            return
        st = styles.get(node)
        if st is None or st.get('display') == 'none':
            return
        if node.name == 'img':
            alt = node.attrs.get('alt', '').strip()
            if alt:
                out.append((f'[{alt}]', st))
            return
        for child in node.children:
            if child.node_type == 'comment':
                continue
            _flatten_inline(child, styles, out)


def _tokenize_run(run_nodes, styles):
    tokens = []
    for item_node in run_nodes:
        frags = []
        _flatten_inline(item_node, styles, frags)
        for text, style in frags:
            if text is BR:
                tokens.append((BR, None))
                continue
            for word in text.split():
                tokens.append((word, style))
    return tokens


def _break_lines(tokens, available_width):
    lines = []
    current = []
    current_width = 0.0
    for word, style in tokens:
        if word is BR:
            lines.append(current)
            current = []
            current_width = 0.0
            continue
        scale = _scale_for(style)
        word_w = font.measure_text(word, scale)
        gap_w = font.measure_text(' ', scale) if current else 0.0
        if current and (current_width + gap_w + word_w > available_width):
            lines.append(current)
            current = [(word, style, scale)]
            current_width = word_w
        else:
            current.append((word, style, scale))
            current_width += gap_w + word_w
    if current:
        lines.append(current)
    return lines


def _build_line_boxes(lines, start_x, start_y, container_width, align):
    boxes = []
    y = start_y
    for line in lines:
        if not line:
            # A blank line from a hard break (<br>, or two in a row) still
            # takes up a line's worth of vertical space.
            lb = LayoutBox(None, None, 'line')
            lb.x, lb.y = start_x, y
            lb.content_width = container_width
            lb.content_height = font.line_height(1)
            boxes.append(lb)
            y += lb.content_height
            continue
        height = max(font.line_height(scale) for (_w, _s, scale) in line)
        line_width = 0.0
        first = True
        for (word, _style, scale) in line:
            if not first:
                line_width += font.measure_text(' ', scale)
            line_width += font.measure_text(word, scale)
            first = False

        shift = 0.0
        if align == 'center':
            shift = max(0.0, (container_width - line_width) / 2.0)
        elif align == 'right':
            shift = max(0.0, container_width - line_width)

        lb = LayoutBox(None, None, 'line')
        lb.x = start_x
        lb.y = y
        lb.content_width = container_width
        lb.content_height = height

        cx = start_x + shift
        first = True
        for (word, style, scale) in line:
            if not first:
                cx += font.measure_text(' ', scale)
            color = style.get('color') if style else 'black'
            lb.fragments.append({'x': cx, 'y': y, 'text': word, 'color': color, 'scale': scale})
            cx += font.measure_text(word, scale)
            first = False
        boxes.append(lb)
        y += height
    return boxes


def _layout_flow_children(node, styles, parent_box, content_x, content_y, content_width):
    cursor_y = content_y
    prev_margin_bottom = 0.0
    is_first_block = True

    def flush(run_nodes):
        nonlocal cursor_y, prev_margin_bottom
        if not run_nodes:
            return
        tokens = _tokenize_run(run_nodes, styles)
        if not tokens:
            return
        # A preceding block sibling's margin-bottom (tracked in
        # prev_margin_bottom, not yet applied to cursor_y) must still push
        # this inline content down -- otherwise text right after a block
        # element with margin-bottom would butt up against it with no gap.
        start_y = cursor_y + prev_margin_bottom
        align = (parent_box.style.get('text-align') if parent_box.style else None) or 'left'
        lines = _break_lines(tokens, content_width)
        line_boxes = _build_line_boxes(lines, content_x, start_y, content_width, align)
        parent_box.children.extend(line_boxes)
        if line_boxes:
            last = line_boxes[-1]
            cursor_y = last.y + last.content_height
        prev_margin_bottom = 0.0

    run_nodes = []
    for child in node.children:
        if child.node_type == 'comment':
            continue
        if _is_inline_level(child, styles):
            # Whitespace-only text contributes zero words in _tokenize_run,
            # so it's harmless to always collect it here -- no special
            # leading/trailing-whitespace bookkeeping needed.
            run_nodes.append(child)
            continue
        if child.node_type != 'element':
            continue
        cstyle = styles.get(child)
        if cstyle is None or cstyle.get('display') == 'none':
            continue

        flush(run_nodes)
        run_nodes = []

        peek = _resolve_box_model(cstyle, content_width)
        child_margin_top, _mr, child_margin_bottom, _ml = peek['margin']
        applied_top = child_margin_top if is_first_block else max(prev_margin_bottom, child_margin_top)
        child_y = cursor_y + applied_top - child_margin_top

        child_box = _layout_block_container(child, cstyle, styles, content_x, child_y, content_width)
        parent_box.children.append(child_box)

        cursor_y = child_box.y + child_box.border_box_height()
        prev_margin_bottom = child_margin_bottom
        is_first_block = False

    flush(run_nodes)

    return max(0.0, (cursor_y + prev_margin_bottom) - content_y)


def _layout_block_container(node, style, styles, x, y, containing_width):
    box_model = _resolve_box_model(style, containing_width)
    margin_t, _mr, _mb, margin_l = box_model['margin']

    border_box_x = x + margin_l
    border_box_y = y + margin_t

    if box_model['width'] is not None:
        content_width = box_model['width']
    else:
        _bt, br, _bb, bl = box_model['border']
        pt, pr, pb, pl = box_model['padding']
        _mt, mr, mb, ml = box_model['margin']
        content_width = max(0.0, containing_width - ml - mr - bl - br - pl - pr)

    box = LayoutBox(node, style, 'block')
    box.margin = box_model['margin']
    box.border = box_model['border']
    box.padding = box_model['padding']
    box.background = box_model['background']
    box.border_color = box_model['border_color']
    box.border_style = box_model['border_style']
    box.x = border_box_x
    box.y = border_box_y
    box.content_width = content_width

    content_x, content_y = box.content_origin()

    if style is not None and style.get('display') == 'flex':
        used_height = layout_flex_children(
            node, styles, box, content_x, content_y, content_width, box_model['height'],
        )
    else:
        used_height = _layout_flow_children(node, styles, box, content_x, content_y, content_width)

    box.content_height = box_model['height'] if box_model['height'] is not None else used_height
    return box


def layout_document(document, styles, viewport_width=800):
    return _layout_block_container(document, None, styles, 0.0, 0.0, float(viewport_width))


# --- Flexbox (stretch feature) ------------------------------------------
#
# A single-line flex container: flex-direction row|column, justify-content
# (flex-start/center/flex-end/space-between/space-around), align-items
# (flex-start/center/flex-end/stretch), gap, and flex-grow. Scoped
# honestly: row-direction items with `width: auto` and no flex-grow get an
# approximate basis from measuring their own text content (there's no
# cheap equivalent of a real "shrink-to-fit" min/max-content pass here);
# column-direction items measure their true basis with a real layout pass
# at the resolved cross-width first, since a content-driven height *is*
# just normal block layout, then get repositioned rather than re-laid-out.

def _parse_number(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _measure_natural_width(node, styles):
    tokens = _tokenize_run([node], styles)
    total = 0.0
    first = True
    for word, style in tokens:
        if word is BR:
            continue
        scale = _scale_for(style)
        if not first:
            total += font.measure_text(' ', scale)
        total += font.measure_text(word, scale)
        first = False
    return total


def _layout_flex_item(node, style, styles, x, y, forced_content_width):
    box_model = _resolve_box_model(style, forced_content_width)
    margin_t, _mr, _mb, margin_l = box_model['margin']
    box = LayoutBox(node, style, 'block')
    box.margin = box_model['margin']
    box.border = box_model['border']
    box.padding = box_model['padding']
    box.background = box_model['background']
    box.border_color = box_model['border_color']
    box.border_style = box_model['border_style']
    box.x = x + margin_l
    box.y = y + margin_t
    box.content_width = forced_content_width
    content_x, content_y = box.content_origin()
    used_height = _layout_flow_children(node, styles, box, content_x, content_y, forced_content_width)
    box.content_height = box_model['height'] if box_model['height'] is not None else used_height
    return box


def _translate_box(box, dx, dy):
    box.x += dx
    box.y += dy
    for frag in box.fragments:
        # Line-box text is painted from each fragment's own stored x/y
        # (not the box's), since a line box can hold many differently
        # colored/sized words -- so those need shifting too, or text left
        # over from the pre-repositioning measurement pass renders in the
        # wrong place while its background/border move correctly.
        frag['x'] += dx
        frag['y'] += dy
    for child in box.children:
        _translate_box(child, dx, dy)


def layout_flex_children(node, styles, parent_box, content_x, content_y, content_width, definite_height):
    style = parent_box.style
    direction = ((style.get('flex-direction') if style else None) or 'row').strip()
    justify = ((style.get('justify-content') if style else None) or 'flex-start').strip()
    align = ((style.get('align-items') if style else None) or 'stretch').strip()
    font_size = _font_size_of(style)
    gap = to_px(style.get('gap') if style else None, font_size=font_size) or 0.0

    items = []
    for child in node.children:
        if child.node_type != 'element':
            continue
        cstyle = styles.get(child)
        if cstyle is None or cstyle.get('display') == 'none':
            continue
        items.append((child, cstyle))

    if not items:
        return 0.0

    if direction == 'column':
        return _layout_flex_column(items, styles, parent_box, content_x, content_y,
                                    content_width, justify, align, gap, definite_height)
    return _layout_flex_row(items, styles, parent_box, content_x, content_y,
                             content_width, justify, align, gap, definite_height)


def _outer_horizontal(box_model):
    _mt, mr, _mb, ml = box_model['margin']
    _bt, br, _bb, bl = box_model['border']
    _pt, pr, _pb, pl = box_model['padding']
    return ml + mr + bl + br + pl + pr


def _outer_vertical(box_model):
    mt, _mr, mb, _ml = box_model['margin']
    bt, _br, bb, _bl = box_model['border']
    pt, _pr, pb, _pl = box_model['padding']
    return mt + mb + bt + bb + pt + pb


def _justify_offsets(free_space, justify, count):
    """Returns (leading_offset, extra_gap_between_items)."""
    if justify == 'center':
        return free_space / 2.0, 0.0
    if justify == 'flex-end':
        return free_space, 0.0
    if justify == 'space-between' and count > 1:
        return 0.0, free_space / (count - 1)
    if justify == 'space-around' and count > 0:
        pad = free_space / count
        return pad / 2.0, pad
    return 0.0, 0.0


def _layout_flex_row(items, styles, parent_box, content_x, content_y, content_width,
                      justify, align, gap, definite_height):
    resolved = []
    total_grow = 0.0
    for child, cstyle in items:
        box_model = _resolve_box_model(cstyle, content_width)
        grow = max(0.0, _parse_number(cstyle.get('flex-grow'), 0.0))
        if box_model['width'] is not None:
            basis = box_model['width']
        elif grow > 0:
            basis = 0.0
        else:
            basis = _measure_natural_width(child, styles)
        resolved.append({'child': child, 'cstyle': cstyle, 'box_model': box_model,
                          'grow': grow, 'basis': basis})
        total_grow += grow

    total_gap = gap * (len(resolved) - 1) if len(resolved) > 1 else 0.0
    fixed_total = sum(r['basis'] + _outer_horizontal(r['box_model']) for r in resolved)
    remaining = max(0.0, content_width - fixed_total - total_gap)

    for r in resolved:
        r['main_size'] = r['basis'] + (remaining * (r['grow'] / total_grow) if total_grow > 0 else 0.0)

    used_main = sum(r['main_size'] + _outer_horizontal(r['box_model']) for r in resolved) + total_gap
    free_space = max(0.0, content_width - used_main) if total_grow == 0 else 0.0
    leading, extra_gap = _justify_offsets(free_space, justify, len(resolved))

    cross_extent = definite_height if definite_height is not None else 0.0
    items_boxes = []
    for r in resolved:
        item_box = _layout_flex_item(r['child'], r['cstyle'], styles, 0.0, 0.0, r['main_size'])
        items_boxes.append(item_box)
        cross_extent = max(cross_extent, item_box.border_box_height())

    cursor_x = content_x + leading
    for i, (r, item_box) in enumerate(zip(resolved, items_boxes)):
        box_model = r['box_model']
        target_x = cursor_x
        h = item_box.border_box_height()
        if align == 'center':
            target_y = content_y + (cross_extent - h) / 2.0
        elif align == 'flex-end':
            target_y = content_y + (cross_extent - h)
        else:
            target_y = content_y
            if align == 'stretch':
                item_box.content_height += max(0.0, cross_extent - h)
        dx = target_x - item_box.x
        dy = target_y - item_box.y
        _translate_box(item_box, dx, dy)
        parent_box.children.append(item_box)
        cursor_x += r['main_size'] + _outer_horizontal(box_model)
        if i < len(resolved) - 1:
            cursor_x += gap + extra_gap

    return cross_extent


def _layout_flex_column(items, styles, parent_box, content_x, content_y, content_width,
                         justify, align, gap, definite_height):
    resolved = []
    total_grow = 0.0
    for child, cstyle in items:
        box_model = _resolve_box_model(cstyle, content_width)
        if box_model['width'] is not None:
            item_width = box_model['width']
        else:
            item_width = max(0.0, content_width - _outer_horizontal(box_model))
        temp_box = _layout_flex_item(child, cstyle, styles, 0.0, 0.0, item_width)
        grow = max(0.0, _parse_number(cstyle.get('flex-grow'), 0.0))
        basis = box_model['height'] if box_model['height'] is not None else temp_box.content_height
        resolved.append({'child': child, 'cstyle': cstyle, 'box_model': box_model,
                          'item_width': item_width, 'grow': grow, 'basis': basis,
                          'temp_box': temp_box})
        total_grow += grow

    total_gap = gap * (len(resolved) - 1) if len(resolved) > 1 else 0.0
    fixed_total = sum(r['basis'] + _outer_vertical(r['box_model']) for r in resolved)

    if definite_height is not None and total_grow > 0:
        remaining = max(0.0, definite_height - fixed_total - total_gap)
    else:
        remaining = 0.0

    for r in resolved:
        r['main_size'] = r['basis'] + (remaining * (r['grow'] / total_grow) if total_grow > 0 else 0.0)
        if r['main_size'] != r['basis']:
            # flex-grow changed the main size (height): the earlier measurement
            # pass no longer reflects the box's real content height.
            r['temp_box'].content_height = r['main_size']

    used_main = sum(r['main_size'] + _outer_vertical(r['box_model']) for r in resolved) + total_gap
    container_extent = definite_height if definite_height is not None else used_main
    free_space = max(0.0, container_extent - used_main) if definite_height is not None else 0.0
    leading, extra_gap = _justify_offsets(free_space, justify, len(resolved))

    cursor_y = content_y + leading
    for i, r in enumerate(resolved):
        box_model = r['box_model']
        outer_w = r['item_width'] + _outer_horizontal(box_model)
        free_x = max(0.0, content_width - outer_w)
        if align == 'center':
            target_x = content_x + free_x / 2.0
        elif align == 'flex-end':
            target_x = content_x + free_x
        else:
            target_x = content_x

        item_box = r['temp_box']
        dx = target_x - item_box.x
        dy = cursor_y - item_box.y
        _translate_box(item_box, dx, dy)
        parent_box.children.append(item_box)

        cursor_y += r['main_size'] + _outer_vertical(box_model)
        if i < len(resolved) - 1:
            cursor_y += gap + extra_gap

    return cursor_y - content_y
