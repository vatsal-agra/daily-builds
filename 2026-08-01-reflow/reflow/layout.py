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


def _flatten_inline(node, styles, out):
    if node.node_type == 'text':
        out.append((node.data, styles.get(node)))
        return
    if node.node_type == 'element':
        st = styles.get(node)
        if st is None or st.get('display') == 'none':
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
            for word in text.split():
                tokens.append((word, style))
    return tokens


def _break_lines(tokens, available_width):
    lines = []
    current = []
    current_width = 0.0
    for word, style in tokens:
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
        align = (parent_box.style.get('text-align') if parent_box.style else None) or 'left'
        lines = _break_lines(tokens, content_width)
        line_boxes = _build_line_boxes(lines, content_x, cursor_y, content_width, align)
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
            if child.node_type == 'text' and child.data.strip() == '' and not run_nodes:
                # Drop leading pure-whitespace text (formatting indentation)
                # so it doesn't force an empty run before real content.
                if not child.data:
                    continue
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

    used_height = _layout_flow_children(node, styles, box, content_x, content_y, content_width)

    box.content_height = box_model['height'] if box_model['height'] is not None else used_height
    return box


def layout_document(document, styles, viewport_width=800):
    return _layout_block_container(document, None, styles, 0.0, 0.0, float(viewport_width))
