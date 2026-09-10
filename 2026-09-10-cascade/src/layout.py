"""The layout engine: computed-style DOM -> a positioned box tree.

Box.x/y/width/height are the BORDER BOX (matching the real DOM's
`getBoundingClientRect()`, which is exactly what makes the Chromium
differential oracle in tests/test_diff_oracle.py possible). Implements:

  * the CSS box model (content/padding/border/margin, `box-sizing:
    content-box` -- the CSS default)
  * block formatting context: vertical stacking, width resolution against
    the containing block (including auto-margin centering), and
    adjoining-sibling margin collapsing (the common case; parent/child
    collapsing and negative margins are a documented scope cut -- see
    REVIEW.md)
  * inline formatting context: text flattened to word tokens (inheriting
    each source element's computed style), line-box wrapping to the
    available width, <br> forced breaks, inline-block atomic boxes
  * list-item bullet markers
  * a flexbox subset (see flexbox.py): row/column, justify-content,
    align-items, flex-grow/flex-shrink/flex-basis distribution

Layout happens in two passes: first every box gets coordinates RELATIVE to
its own containing block's content-box origin (0, 0); `finalize_positions`
then walks the tree once, accumulating ancestor offsets, to produce final
absolute page coordinates. That separation is what keeps the block/inline/
flex code from having to thread absolute offsets through every recursive
call.
"""

from css_values import parse_color, parse_font_weight, parse_length
from dom import Element, Text
from font import char_advance, line_height_for, measure_text

BLOCK_LEVEL = {"block", "list-item", "flex"}
INLINE_LEVEL = {"inline", "inline-block"}


class EdgeSizes:
    __slots__ = ("top", "right", "bottom", "left")

    def __init__(self, top=0.0, right=0.0, bottom=0.0, left=0.0):
        self.top, self.right, self.bottom, self.left = top, right, bottom, left


class EdgeSizesColor:
    __slots__ = ("top", "right", "bottom", "left")

    def __init__(self):
        self.top = self.right = self.bottom = self.left = (0, 0, 0, 255)


class Box:
    def __init__(self, box_type, node=None, style=None, anonymous=False):
        self.box_type = box_type  # 'block' | 'inline-block' | 'flex' | 'line' | 'text'
        self.node = node
        self.style = style or {}
        self.anonymous = anonymous
        self.children = []
        self.x = self.y = 0.0
        self.width = self.height = 0.0  # border-box outer size
        self.margin = EdgeSizes()
        self.border = EdgeSizes()
        self.padding = EdgeSizes()
        self.text = None
        self.font_size = 16.0
        self.color = (0, 0, 0, 255)
        self.font_weight = 400
        self.background_color = (0, 0, 0, 0)
        self.border_color = EdgeSizesColor()
        self._content_h = 0.0

    @property
    def content_width(self):
        return self.width - self.border.left - self.border.right - self.padding.left - self.padding.right

    @property
    def content_height(self):
        return self.height - self.border.top - self.border.bottom - self.padding.top - self.padding.bottom

    def iter_boxes(self):
        yield self
        for c in self.children:
            yield from c.iter_boxes()

    def __repr__(self):
        tag = self.node.tag if isinstance(self.node, Element) else ("anon" if self.anonymous else "text")
        return f"Box({self.box_type}:{tag} {self.x:.0f},{self.y:.0f} {self.width:.0f}x{self.height:.0f})"


# ---------------------------------------------------------------------------
# Style resolution helpers
# ---------------------------------------------------------------------------

def display_of(style):
    return style.get("display", "inline")


def is_rendered(node):
    if isinstance(node, Element):
        return display_of(node.computed_style) != "none"
    if isinstance(node, Text):
        return True
    return False  # comments etc.


def visible_children(node):
    return [c for c in node.children if is_rendered(c) and not (isinstance(c, Text) and c.data == "")]


def resolve_border_width(style, side, font_size):
    if style.get(f"border-{side}-style", "none") == "none":
        return 0.0
    return parse_length(style.get(f"border-{side}-width", "0px"), font_size).resolve(0)


def box_edges(style, font_size, cbw):
    border = EdgeSizes(
        resolve_border_width(style, "top", font_size),
        resolve_border_width(style, "right", font_size),
        resolve_border_width(style, "bottom", font_size),
        resolve_border_width(style, "left", font_size),
    )
    padding = EdgeSizes(
        parse_length(style.get("padding-top", "0px"), font_size).resolve(cbw),
        parse_length(style.get("padding-right", "0px"), font_size).resolve(cbw),
        parse_length(style.get("padding-bottom", "0px"), font_size).resolve(cbw),
        parse_length(style.get("padding-left", "0px"), font_size).resolve(cbw),
    )
    return border, padding


def set_visual_props(box, style, font_size):
    box.font_size = font_size
    box.color = parse_color(style.get("color", "#000000"))
    box.font_weight = parse_font_weight(style.get("font-weight", "normal"))
    box.background_color = parse_color(style.get("background-color", "transparent"), default=(0, 0, 0, 0))
    for side in ("top", "right", "bottom", "left"):
        raw = style.get(f"border-{side}-color", "currentcolor")
        # border-color's real CSS initial value is `currentcolor`: an
        # unspecified border (e.g. `border: 2px solid` with no color)
        # takes the element's own text color, not a fixed black.
        if raw.strip().lower() == "currentcolor":
            setattr(box.border_color, side, box.color)
        else:
            setattr(box.border_color, side, parse_color(raw))


def resolve_box_metrics(style, cbw, font_size):
    """Returns (content_width, margin: EdgeSizes, border: EdgeSizes,
    padding: EdgeSizes) per CSS 2.1 section 10.3.3's width/margin
    resolution algorithm for block-level non-replaced boxes."""
    border, padding = box_edges(style, font_size, cbw)
    fixed = border.left + border.right + padding.left + padding.right

    margin_left_len = parse_length(style.get("margin-left", "0px"), font_size)
    margin_right_len = parse_length(style.get("margin-right", "0px"), font_size)
    width_len = parse_length(style.get("width", "auto"), font_size)

    if not width_len.auto:
        content_w = width_len.resolve(cbw)
        remaining = cbw - fixed - content_w
        if margin_left_len.auto and margin_right_len.auto:
            ml = mr = max(remaining / 2.0, 0.0)
        elif margin_left_len.auto:
            mr = margin_right_len.resolve(cbw)
            ml = remaining - mr
        elif margin_right_len.auto:
            ml = margin_left_len.resolve(cbw)
            mr = remaining - ml
        else:
            ml = margin_left_len.resolve(cbw)
            mr = margin_right_len.resolve(cbw)
    else:
        ml = 0.0 if margin_left_len.auto else margin_left_len.resolve(cbw)
        mr = 0.0 if margin_right_len.auto else margin_right_len.resolve(cbw)
        content_w = max(cbw - fixed - ml - mr, 0.0)

    content_w = max(content_w, 0.0)
    mtop = parse_length(style.get("margin-top", "0px"), font_size).resolve(cbw)
    mbot = parse_length(style.get("margin-bottom", "0px"), font_size).resolve(cbw)
    margin = EdgeSizes(mtop, mr, mbot, ml)
    return content_w, margin, border, padding


# ---------------------------------------------------------------------------
# Box-tree construction / layout
# ---------------------------------------------------------------------------

def build_root(html_root, viewport_width):
    """html_root: the <html> DOM Element. Lays out the whole document
    against a viewport of the given width and returns the root Box in
    absolute page coordinates."""
    style = html_root.computed_style
    font_size = parse_length(style.get("font-size", "16px"), 16.0).resolve(0) or 16.0
    root = Box("block", node=html_root, style=style)
    set_visual_props(root, style, font_size)

    content_w, margin, border, padding = resolve_box_metrics(style, viewport_width, font_size)
    root.margin, root.border, root.padding = margin, border, padding
    # the <html> element's own containing block is the viewport, whose
    # height this engine doesn't model (no scroll/viewport-height concept),
    # so its containing-block height is indefinite (cbh=None): a percentage
    # `height` on <html>/<body> itself falls back to auto, matching how a
    # real browser treats a percentage height with no definite ancestor.
    own_definite_h = _resolve_definite_height(style, font_size, None)
    layout_block_children_into(root, content_w, font_size, cbh=own_definite_h)
    content_h = own_definite_h if own_definite_h is not None else root._content_h
    root.width = content_w + border.left + border.right + padding.left + padding.right
    root.height = content_h + border.top + border.bottom + padding.top + padding.bottom
    root.x = margin.left
    root.y = margin.top
    _finalize_positions(root, 0.0, 0.0)
    return root


def _finalize_positions(box, parent_content_x, parent_content_y):
    box.x = parent_content_x + box.x
    box.y = parent_content_y + box.y
    cx = box.x + box.border.left + box.padding.left
    cy = box.y + box.border.top + box.padding.top
    for child in box.children:
        _finalize_positions(child, cx, cy)


def _make_element_box(el, font_size_parent, style_override=None):
    style = style_override if style_override is not None else el.computed_style
    display = display_of(style)
    font_size = parse_length(style.get("font-size", "16px"), font_size_parent).resolve(0) or font_size_parent
    box_type = "flex" if display == "flex" else ("inline-block" if display == "inline-block" else "block")
    box = Box(box_type, node=el, style=style)
    box.font_size = font_size
    set_visual_props(box, style, font_size)
    return box


def _resolve_definite_height(style, font_size, cbh):
    """A CSS percentage height only resolves against a containing block
    with a DEFINITE height (CSS 2.1 10.5); against an auto-height
    container it computes to 'auto' instead. `cbh` is the containing
    block's own resolved content height, or None if that's auto/unknown.
    Returns a resolved px height, or None if the height is (effectively)
    auto and should come from content instead."""
    height_len = parse_length(style.get("height", "auto"), font_size)
    if height_len.auto:
        return None
    if height_len.percent is not None:
        return height_len.resolve(cbh) if cbh is not None else None
    return height_len.px


def layout_block_box(el, cbw, parent_font_size, style_override=None, cbh=None):
    """Lays out one element as a block-level (or inline-block/flex) box.
    Returns a Box positioned RELATIVE to its future parent's content
    origin (box.x = its resolved margin-left; box.y left at 0, set later
    by the caller's stacking/positioning pass). `cbh`: this box's OWN
    containing block's definite content height (for resolving a
    percentage `height` on this box), or None if indefinite."""
    box = _make_element_box(el, parent_font_size, style_override)
    font_size = box.font_size
    content_w, margin, border, padding = resolve_box_metrics(box.style, cbw, font_size)
    box.margin, box.border, box.padding = margin, border, padding

    own_definite_h = _resolve_definite_height(box.style, font_size, cbh)

    if box.box_type == "flex":
        from flexbox import layout_flex_container
        layout_flex_container(box, content_w, font_size, cbh=own_definite_h)
    else:
        layout_block_children_into(box, content_w, font_size, cbh=own_definite_h)

    content_h = own_definite_h if own_definite_h is not None else box._content_h

    box.width = content_w + border.left + border.right + padding.left + padding.right
    box.height = content_h + border.top + border.bottom + padding.top + padding.bottom
    box.x = margin.left
    box.y = 0.0
    return box


def relayout_at_outer_width(box, new_outer_width, font_size, cbh=None):
    """Re-runs this box's own content layout at a specific final outer
    (border-box) width -- used by flexbox when the flex algorithm assigns
    an item a main/cross size different from its hypothetical size."""
    new_content_w = max(new_outer_width - box.border.left - box.border.right
                         - box.padding.left - box.padding.right, 0.0)
    own_definite_h = _resolve_definite_height(box.style, font_size, cbh)
    if box.box_type == "flex":
        from flexbox import layout_flex_container
        layout_flex_container(box, new_content_w, font_size, cbh=own_definite_h)
    else:
        layout_block_children_into(box, new_content_w, font_size, cbh=own_definite_h)
    content_h = own_definite_h if own_definite_h is not None else box._content_h
    box.width = new_outer_width
    box.height = content_h + box.border.top + box.border.bottom + box.padding.top + box.padding.bottom


def layout_block_children_into(container_box, cbw, font_size, cbh=None):
    """Groups container_box's DOM children into block boxes and anonymous
    inline-run block boxes, lays each out, stacks them vertically with
    margin collapsing, and sets container_box.children + ._content_h.
    Children get positions RELATIVE to container_box's own content origin.
    `cbh`: container_box's own definite content height, passed to block
    children as their containing-block height (for their percentage
    `height`, if any)."""
    node = container_box.node
    kids = visible_children(node) if node is not None else []

    groups = []
    run = []
    for c in kids:
        if isinstance(c, Element) and display_of(c.computed_style) in BLOCK_LEVEL:
            if run:
                groups.append(("inline-run", run))
                run = []
            groups.append(("block", c))
        else:
            if isinstance(c, Text) and c.data.strip() == "" and not run:
                continue
            run.append(c)
    if run and any(not (isinstance(n, Text) and n.data.strip() == "") for n in run):
        groups.append(("inline-run", run))

    if (node is not None and display_of(node.computed_style) == "list-item"
            and node.computed_style.get("list-style-type", "disc") != "none"):
        marker = Text("• ")
        if groups and groups[0][0] == "inline-run":
            groups[0] = ("inline-run", [marker] + groups[0][1])
        else:
            groups.insert(0, ("inline-run", [marker]))

    cursor_y = 0.0
    prev_margin_bottom = 0.0
    first = True
    child_boxes = []

    for kind, payload in groups:
        if kind == "block":
            child = layout_block_box(payload, cbw, font_size, cbh=cbh)
            top_gap = child.margin.top if first else max(prev_margin_bottom, child.margin.top)
            cursor_y += top_gap
            child.y = cursor_y
            cursor_y += child.height
            prev_margin_bottom = child.margin.bottom
        else:
            child = layout_inline_run(payload, cbw, font_size, container_box.style, cbh=cbh)
            top_gap = 0.0 if first else prev_margin_bottom
            cursor_y += top_gap
            child.y = cursor_y
            child.x = 0.0
            cursor_y += child.height
            prev_margin_bottom = 0.0
        first = False
        child_boxes.append(child)

    container_box.children = child_boxes
    container_box._content_h = cursor_y


# ---------------------------------------------------------------------------
# Inline formatting context
# ---------------------------------------------------------------------------

class InlineToken:
    __slots__ = ("kind", "text", "width", "height", "style_ref", "box")

    def __init__(self, kind, text=None, width=0.0, height=0.0, style_ref=None, box=None):
        self.kind = kind  # 'word' | 'break' | 'box'
        self.text = text
        self.width = width
        self.height = height
        self.style_ref = style_ref
        self.box = box


def _collect_inline_tokens(nodes, cbw, font_size_parent, style_parent, tokens, cbh=None):
    for n in nodes:
        if isinstance(n, Text):
            for w in n.data.split():
                fs = font_size_parent
                tokens.append(InlineToken(
                    "word", text=w, width=measure_text(w, fs), height=fs,
                    style_ref=(fs, parse_color(style_parent.get("color", "#000")),
                               parse_font_weight(style_parent.get("font-weight", "normal")))))
        elif isinstance(n, Element):
            if not is_rendered(n):
                continue
            if n.tag == "br":
                tokens.append(InlineToken("break"))
                continue
            style = n.computed_style
            fs = parse_length(style.get("font-size", "16px"), font_size_parent).resolve(0) or font_size_parent
            if display_of(style) == "inline-block":
                override = None
                width_len = parse_length(style.get("width", "auto"), fs)
                if width_len.auto and not any(isinstance(c, Element) for c in n.children):
                    # shrink-to-fit approximation for a text-only leaf: a
                    # block box's auto width normally FILLS its containing
                    # block, but inline-block's auto width should instead
                    # hug its content (the real spec algorithm is
                    # min/max-content sizing; we approximate with the
                    # measured text-run width, same approach flexbox.py
                    # uses for its own fit-content items).
                    text = n.text_content().strip()
                    approx_content = measure_text(text, fs) if text else 0.0
                    override = dict(style)
                    override["width"] = f"{approx_content}px"
                box = layout_block_box(n, cbw, font_size_parent, style_override=override, cbh=cbh)
                tokens.append(InlineToken("box", width=box.width + box.margin.left + box.margin.right,
                                           height=box.height, box=box))
            else:
                _collect_inline_tokens(visible_children(n), cbw, fs, style, tokens, cbh=cbh)


def layout_inline_run(nodes, cbw, font_size, parent_style, cbh=None):
    """Lays a run of inline-level nodes out into line boxes, inside an
    anonymous block-level container box positioned relative to (0, 0).
    `cbh` is threaded through only so a nested inline-block's own
    percentage `height` can resolve against the real containing block."""
    container = Box("block", node=None, style={}, anonymous=True)
    container.font_size = font_size
    tokens = []
    _collect_inline_tokens(nodes, cbw, font_size, parent_style, tokens, cbh=cbh)

    text_align = parent_style.get("text-align", "left")
    space_w = char_advance(font_size)
    default_line_h = line_height_for(font_size, parent_style.get("line-height", "normal"))

    lines = []
    cur = []
    cur_w = 0.0
    cur_h = default_line_h

    def flush():
        nonlocal cur, cur_w, cur_h
        if cur or not lines:
            lines.append((cur, cur_w, cur_h))
        cur, cur_w, cur_h = [], 0.0, default_line_h

    for tok in tokens:
        if tok.kind == "break":
            flush()
            continue
        add_w = tok.width + (space_w if cur else 0.0)
        if cur and cur_w + add_w > cbw + 1e-6:
            flush()
            add_w = tok.width
        cur.append(tok)
        cur_w += add_w
        if tok.kind == "box":
            cur_h = max(cur_h, tok.height)
    flush()
    if not tokens:
        lines = []

    y = 0.0
    line_boxes = []
    for line_tokens, lw, lh in lines:
        line_box = Box("line", anonymous=True)
        line_box.y = y
        line_box.height = lh
        line_box.width = cbw
        extra = max(cbw - lw, 0.0)
        if text_align == "center":
            start_x = extra / 2.0
        elif text_align == "right":
            start_x = extra
        else:
            start_x = 0.0
        x = start_x
        n_gaps = max(len(line_tokens) - 1, 0)
        gap = space_w
        if text_align == "justify" and n_gaps > 0 and extra > 0:
            gap = space_w + extra / n_gaps
            x = 0.0
        for i, tok in enumerate(line_tokens):
            if tok.kind == "word":
                fs, color, weight = tok.style_ref
                tb = Box("text")
                tb.text = tok.text
                tb.font_size = fs
                tb.color = color
                tb.font_weight = weight
                tb.x, tb.y = x, 0.0
                tb.width, tb.height = tok.width, lh
                line_box.children.append(tb)
            else:
                tok.box.x = x + tok.box.margin.left
                tok.box.y = lh - tok.height
                line_box.children.append(tok.box)
            x += tok.width + (gap if i < len(line_tokens) - 1 else 0.0)
        line_boxes.append(line_box)
        y += lh

    container.children = line_boxes
    container._content_h = y
    container.width = cbw
    container.height = y
    container.x = 0.0
    container.y = 0.0
    return container
