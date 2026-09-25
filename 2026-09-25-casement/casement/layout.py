"""The box tree builder and layout engine: block/inline formatting contexts,
flexbox, and basic relative/absolute positioning.

Coordinate model: every LayoutBox's `dims.x`/`dims.y` are the box's content
box origin in absolute (page) coordinates. Because a block box's width and
auto-height never depend on its own final position, box model resolution
(margins/border/padding/width) can run before position is known -- but
laying out a box's *children* absolutely does require the box's own final
(x, y) first, so `layout_children_in_flow` always assigns a child's (x, y)
before recursing into it. Flexbox is the one context where an item's final
main-axis position depends on sibling sizing that isn't known until every
item in the line has already been sized (and its subtree laid out at a
placeholder origin): `layout_flex` handles that with a post-hoc
`translate_box_tree` pass shifting an item's whole already-laid-out subtree
by its real position once the line's geometry is known.

Scope decisions (disclosed up front, see PLAN.md and REVIEW.md):
  * Inline elements (span/a/strong/em/b/i) contribute their computed color
    and font-weight to the text they wrap, but do not themselves get a
    painted background/border box split across lines -- only block,
    inline-block, flex, and replaced (img) boxes are directly painted.
  * Margin collapsing implements the two most visible real-world cases:
    adjacent in-flow block siblings, and a block's own top margin
    collapsing with its first in-flow child's top margin (the classic
    "why isn't there a gap above my <h1>" case). The escaped child margin
    is absorbed at that one level rather than bubbled further up through
    multiple ancestors (real CSS keeps collapsing outward through any
    number of borderless/paddingless ancestors) -- avoided here because
    doing that correctly requires resolving each ancestor's own width
    before its margin can be percentage-resolved, which is circular with
    the position computation that needs the margin first. Bottom/last-
    child collapsing and empty-block self-collapsing are not implemented
    either.
  * Flexbox column-direction sizing is best-effort (no grow/shrink
    distribution along an indefinite main axis, matching real auto-height
    block stacking); row-direction is the fully-solved, fully-tested path.
  * position:absolute resolves offsets against the nearest positioned
    ancestor's content box; an unset offset falls back to 0 (an
    approximation of the CSS "static position" algorithm) rather than the
    full static-position layout pass real browsers run.
  * position:absolute inside a flex container is not pulled out of the
    flex flow (a rare combination in practice); absolute positioning is
    fully supported for block/inline-block containers.
"""

from .dom import Comment, Element, Text
from .font import advance_width

BLOCK_LEVEL_DISPLAYS = {"block", "flex"}
INLINE_LEVEL_DISPLAYS = {"inline", "inline-block"}

class Edges:
    __slots__ = ("top", "right", "bottom", "left")

    def __init__(self, top=0.0, right=0.0, bottom=0.0, left=0.0):
        self.top = top
        self.right = right
        self.bottom = bottom
        self.left = left


class Dimensions:
    __slots__ = ("x", "y", "width", "height", "padding", "border", "margin")

    def __init__(self):
        self.x = 0.0
        self.y = 0.0
        self.width = 0.0
        self.height = 0.0
        self.padding = Edges()
        self.border = Edges()
        self.margin = Edges()

    def border_box(self):
        p, b = self.padding, self.border
        return (
            self.x - p.left - b.left,
            self.y - p.top - b.top,
            self.width + p.left + p.right + b.left + b.right,
            self.height + p.top + p.bottom + b.top + b.bottom,
        )

    def margin_box(self):
        x, y, w, h = self.border_box()
        m = self.margin
        return (x - m.left, y - m.top, w + m.left + m.right, h + m.top + m.bottom)

    def to_dict(self):
        bx, by, bw, bh = self.border_box()
        mx, my, mw, mh = self.margin_box()
        return {
            "content": {"x": self.x, "y": self.y, "w": self.width, "h": self.height},
            "padding": {"top": self.padding.top, "right": self.padding.right,
                        "bottom": self.padding.bottom, "left": self.padding.left},
            "border": {"top": self.border.top, "right": self.border.right,
                       "bottom": self.border.bottom, "left": self.border.left},
            "margin": {"top": self.margin.top, "right": self.margin.right,
                       "bottom": self.margin.bottom, "left": self.margin.left},
            "border_box": {"x": bx, "y": by, "w": bw, "h": bh},
            "margin_box": {"x": mx, "y": my, "w": mw, "h": mh},
        }


class LayoutBox:
    def __init__(self, box_type, node=None, style=None):
        self.box_type = box_type  # block, inline-block, flex, anonymous-block, replaced
        self.node = node
        self.style = style
        self.children = []
        self.dims = Dimensions()
        self.ifc_items = None  # token stream, for anonymous-block IFC roots
        self.lines = None      # computed after layout: list[Line]
        self.absolute_children = []  # position:absolute descendants anchored here
        self.replaced_kind = None  # 'img' etc.

    @property
    def tag(self):
        return self.node.tag if isinstance(self.node, Element) else None


class ContainingBlock:
    __slots__ = ("width", "height")

    def __init__(self, width, height=None):
        self.width = width
        self.height = height


# ---------------------------------------------------------------------------
# Box tree construction
# ---------------------------------------------------------------------------

def build_document_box(document, style_map):
    body = None
    for child in document.children:
        if isinstance(child, Element) and child.tag == "html":
            for c in child.children:
                if isinstance(c, Element) and c.tag == "body":
                    body = c
    if body is None:
        for child in document.children:
            if isinstance(child, Element) and child.tag == "body":
                body = child
    if body is None:
        pseudo = Element("body", {})
        for child in document.children:
            if isinstance(child, Element) and child.tag in ("head", "html"):
                continue
            pseudo.append(child)
        body = pseudo
        if body not in style_map:
            from .style import ComputedStyle, DEFAULTS
            props = dict(DEFAULTS)
            props["display"] = "block"
            style_map[body] = ComputedStyle(props)
    root_absolutes = []
    root_box = build_box_tree(body, style_map, None, root_absolutes)
    return root_box, root_absolutes


def build_box_tree(el, style_map, positioned_ancestor_box=None, root_absolutes=None):
    """Build the box for `el` and its descendants. `positioned_ancestor_box`
    is the nearest ancestor LayoutBox with position != static seen so far
    (None if there isn't one yet, in which case an absolutely-positioned
    descendant is queued into `root_absolutes` to be anchored to the
    document root once the whole tree is built)."""
    if root_absolutes is None:
        root_absolutes = []
    style = style_map.get(el)
    if style is None:
        return None
    display = style.keyword("display")
    if display == "none":
        return None

    if el.tag == "img":
        box = LayoutBox("replaced", el, style)
        box.replaced_kind = "img"
        return box

    is_positioned = style.keyword("position") != "static"
    next_ancestor = None if is_positioned else positioned_ancestor_box

    if display == "flex":
        box = LayoutBox("flex", el, style)
        if is_positioned:
            next_ancestor = box
        for child in el.element_children():
            cstyle = style_map.get(child)
            if cstyle is None or cstyle.keyword("display") == "none":
                continue
            child_box = build_box_tree(child, style_map, next_ancestor, root_absolutes)
            if child_box is None:
                continue
            if cstyle.keyword("position") == "absolute":
                target = next_ancestor.absolute_children if next_ancestor is not None else root_absolutes
                target.append(child_box)
            else:
                box.children.append(child_box)
        return box

    box_type = "inline-block" if display == "inline-block" else "block"
    box = LayoutBox(box_type, el, style)
    if is_positioned:
        next_ancestor = box
    box.children = _build_children_grouped(el, style_map, next_ancestor, root_absolutes)

    if el.tag in ("ul", "ol"):
        _number_list_items(box)
    return box


def _number_list_items(list_box):
    ordered = list_box.tag == "ol"
    index = 1
    for child in list_box.children:
        if isinstance(child, tuple):
            continue
        if child.tag == "li":
            marker = f"{index}." if ordered else "-"
            _prepend_marker(child, marker)
            index += 1


def _prepend_marker(li_box, marker_text):
    style = li_box.style
    if li_box.children and not isinstance(li_box.children[0], tuple) and \
            li_box.children[0].box_type == "anonymous-block":
        anon = li_box.children[0]
        anon.ifc_items[0:0] = [("word", marker_text, style), ("space",)]
    else:
        anon = LayoutBox("anonymous-block", None, style)
        anon.ifc_items = [("word", marker_text, style), ("space",)]
        li_box.children.insert(0, anon)


def _build_children_grouped(el, style_map, positioned_ancestor_box, root_absolutes):
    result = []
    inline_run = []

    def flush():
        if not inline_run:
            return
        has_content = any(
            (isinstance(n, Text) and n.data.strip()) or isinstance(n, Element)
            for n in inline_run
        )
        if has_content:
            anon = LayoutBox("anonymous-block", None, style_map[el])
            anon.ifc_items = flatten_inline_nodes(inline_run, style_map, positioned_ancestor_box, root_absolutes)
            result.append(anon)
        inline_run.clear()

    for child in el.children:
        if isinstance(child, Comment):
            continue
        if isinstance(child, Text):
            inline_run.append(child)
        elif isinstance(child, Element):
            cstyle = style_map.get(child)
            if cstyle is None:
                continue
            disp = cstyle.keyword("display")
            if disp == "none":
                continue
            if cstyle.keyword("position") == "absolute":
                child_box = build_box_tree(child, style_map, positioned_ancestor_box, root_absolutes)
                if child_box is not None:
                    target = positioned_ancestor_box.absolute_children if positioned_ancestor_box is not None else root_absolutes
                    target.append(child_box)
                continue
            if disp in BLOCK_LEVEL_DISPLAYS:
                flush()
                child_box = build_box_tree(child, style_map, positioned_ancestor_box, root_absolutes)
                if child_box is not None:
                    result.append(child_box)
            else:
                inline_run.append(child)
    flush()
    return result


def flatten_inline_nodes(nodes, style_map, positioned_ancestor_box=None, root_absolutes=None):
    """Flatten a run of sibling Text/Element(inline) DOM nodes into a token
    stream: ('word', text, style) | ('space',) | ('break',) |
    ('replaced', box) | ('inline-block', box)."""
    if root_absolutes is None:
        root_absolutes = []
    items = []
    pending_space = [False]

    def visit(node):
        if isinstance(node, Comment):
            return
        if isinstance(node, Text):
            raw = node.data
            if raw == "":
                return
            leading_ws = raw[:1].isspace()
            trailing_ws = raw[-1:].isspace()
            words = raw.split()
            if leading_ws and items:
                pending_space[0] = True
            for idx, w in enumerate(words):
                if idx > 0 or (pending_space[0] and items):
                    items.append(("space",))
                pending_space[0] = False
                items.append(("word", w, style_map[node.parent]))
            if trailing_ws and words:
                pending_space[0] = True
            elif trailing_ws and not words and items:
                pending_space[0] = True
        elif isinstance(node, Element):
            cstyle = style_map.get(node)
            if cstyle is not None and cstyle.keyword("display") == "none":
                return
            if node.tag == "br":
                items.append(("break",))
                pending_space[0] = False
                return
            if node.tag == "img":
                box = LayoutBox("replaced", node, cstyle)
                box.replaced_kind = "img"
                if pending_space[0] and items:
                    items.append(("space",))
                pending_space[0] = False
                items.append(("replaced", box))
                return
            if cstyle is not None and cstyle.keyword("display") == "inline-block":
                box = build_box_tree(node, style_map, positioned_ancestor_box, root_absolutes)
                if box is not None:
                    if pending_space[0] and items:
                        items.append(("space",))
                    pending_space[0] = False
                    items.append(("inline-block", box))
                return
            for c in node.children:
                visit(c)

    for n in nodes:
        visit(n)
    return items


# ---------------------------------------------------------------------------
# Length resolution helpers
# ---------------------------------------------------------------------------

def resolve_len(value, containing_size, auto_val=None):
    if value.kind == "px":
        return value.data
    if value.kind == "pct":
        if containing_size is None:
            return auto_val
        return value.data / 100.0 * containing_size
    if value.kind in ("auto", "none", "normal"):
        return auto_val
    return 0.0


def _px(style, prop, containing_size=0.0, auto_val=0.0):
    return resolve_len(style.length(prop), containing_size, auto_val)


def _border_width(style, side):
    if style.raw(f"border-{side}-style") == "none":
        return 0.0
    v = style.length(f"border-{side}-width")
    return v.data if v.kind == "px" else 0.0


def _resolve_edges(box, cw):
    """Populate margin/border/padding on box.dims from its style. Pure
    function of style + containing width; does not touch x/y/width/height."""
    style = box.style
    d = box.dims
    d.margin.top = _px(style, "margin-top", cw, 0.0)
    d.margin.bottom = _px(style, "margin-bottom", cw, 0.0)
    d.padding.top = _px(style, "padding-top", cw, 0.0)
    d.padding.right = _px(style, "padding-right", cw, 0.0)
    d.padding.bottom = _px(style, "padding-bottom", cw, 0.0)
    d.padding.left = _px(style, "padding-left", cw, 0.0)
    d.border.top = _border_width(style, "top")
    d.border.right = _border_width(style, "right")
    d.border.bottom = _border_width(style, "bottom")
    d.border.left = _border_width(style, "left")
    ml = resolve_len(style.length("margin-left"), cw, None)
    mr = resolve_len(style.length("margin-right"), cw, None)
    return ml, mr


# ---------------------------------------------------------------------------
# Block layout
# ---------------------------------------------------------------------------

def layout_box(box, cb, viewport=None, forced_width=None, forced_height=None):
    if viewport is None:
        viewport = cb
    if box.box_type in ("block", "inline-block"):
        layout_block(box, cb, viewport, forced_width, forced_height)
    elif box.box_type == "flex":
        layout_flex(box, cb, viewport, forced_width, forced_height)
    elif box.box_type == "replaced":
        layout_replaced(box, cb)
    elif box.box_type == "anonymous-block":
        layout_anonymous_block(box, cb, viewport)


def layout_block(box, cb, viewport, forced_width=None, forced_height=None):
    """Lay out `box` given that box.dims.x/box.dims.y (content origin) are
    already set by the caller. `forced_width`/`forced_height`, when given,
    override the box's own CSS width/height entirely -- used by the flex
    algorithm, which computes an item's main size itself and must not let
    the item's own `width`/`height` (if any) silently take back over."""
    style = box.style
    d = box.dims
    cw = cb.width

    ml_v, mr_v = _resolve_edges(box, cw)
    box_sizing = style.keyword("box-sizing")
    edge_w = d.padding.left + d.padding.right + d.border.left + d.border.right
    width_val = style.length("width")

    if forced_width is not None:
        content_w = forced_width
        ml_v = ml_v if ml_v is not None else 0.0
        mr_v = mr_v if mr_v is not None else 0.0
    elif box.box_type == "inline-block" and width_val.kind == "auto":
        content_w = shrink_to_fit_width(box, max(0.0, cw - edge_w))
        ml_v = ml_v if ml_v is not None else 0.0
        mr_v = mr_v if mr_v is not None else 0.0
    elif width_val.kind == "auto":
        avail = cw - edge_w
        ml_v = ml_v if ml_v is not None else 0.0
        mr_v = mr_v if mr_v is not None else 0.0
        content_w = max(0.0, avail - ml_v - mr_v)
    else:
        w = resolve_len(width_val, cw, 0.0)
        if box_sizing == "border-box":
            w = max(0.0, w - edge_w)
        content_w = w
        avail = cw - edge_w - content_w
        if ml_v is None and mr_v is None:
            ml_v = mr_v = max(0.0, avail) / 2.0
        elif ml_v is None:
            ml_v = avail - mr_v
        elif mr_v is None:
            mr_v = avail - ml_v

    if forced_width is None:
        min_w = _px(style, "min-width", cw, 0.0)
        max_w_val = style.length("max-width")
        max_w = resolve_len(max_w_val, cw, None) if max_w_val.kind != "none" else None
        content_w = max(min_w, content_w)
        if max_w is not None:
            content_w = min(content_w, max(max_w, 0.0))

    d.margin.left = ml_v
    d.margin.right = mr_v
    d.width = content_w

    layout_children_in_flow(box, viewport)

    if forced_height is not None:
        d.height = forced_height
    else:
        height_val = style.length("height")
        if height_val.kind == "px":
            d.height = height_val.data
        elif height_val.kind == "pct" and cb.height is not None:
            d.height = height_val.data / 100.0 * cb.height

    resolve_absolute_children(box, viewport)


def layout_children_in_flow(box, viewport):
    d = box.dims
    content_x = d.x
    flow_y = d.y  # next available border-box top (pre-collapse)
    prev_margin_bottom = 0.0
    first = True
    children = box.children

    for child in children:
        child_cb = ContainingBlock(width=d.width, height=None)
        if child.box_type == "anonymous-block":
            child.dims.x = content_x
            child.dims.y = flow_y
            layout_anonymous_block(child, child_cb, viewport)
            flow_y += child.dims.height
            prev_margin_bottom = 0.0
            first = False
            continue

        _resolve_edges(child, d.width)
        effective_margin_top = child.dims.margin.top
        collapsed_here = first and d.border.top == 0 and d.padding.top == 0
        if collapsed_here:
            effective_margin_top = 0.0
        gap = _collapse(prev_margin_bottom, effective_margin_top)
        border_box_top = flow_y + gap

        child.dims.x = content_x + child.dims.margin.left + child.dims.border.left + child.dims.padding.left
        child.dims.y = border_box_top + child.dims.border.top + child.dims.padding.top

        layout_box(child, child_cb, viewport)

        # Relative offset is purely visual -- next-sibling flow position
        # must be computed from the pre-offset box, so this runs last.
        border_box_bottom = child.dims.y + child.dims.height + child.dims.padding.bottom + child.dims.border.bottom
        flow_y = border_box_bottom
        prev_margin_bottom = child.dims.margin.bottom
        first = False
        apply_relative_offset(child, d.width)

    d.height = max(0.0, flow_y - d.y)


def apply_relative_offset(box, cw, ch=None):
    """position:relative only ever shifts what's painted -- it never
    affects where the box's normal-flow siblings/parent think it is, so
    this must run strictly after the box's flow position is finalized."""
    style = box.style
    if style is None or style.keyword("position") != "relative":
        return
    left = resolve_len(style.length("left"), cw, None)
    right = resolve_len(style.length("right"), cw, None)
    top = resolve_len(style.length("top"), ch, None)
    bottom = resolve_len(style.length("bottom"), ch, None)
    dx = left if left is not None else (-right if right is not None else 0.0)
    dy = top if top is not None else (-bottom if bottom is not None else 0.0)
    if dx or dy:
        translate_box_tree(box, dx, dy)


def _collapse(a, b):
    if a >= 0 and b >= 0:
        return max(a, b)
    if a < 0 and b < 0:
        return min(a, b)
    return a + b


def resolve_absolute_children(box, viewport):
    d = box.dims
    resolve_absolutes_against(box.absolute_children, d.x, d.y, d.width, d.height, viewport)


def resolve_absolutes_against(abs_boxes, cb_x, cb_y, cb_w, cb_h, viewport):
    """Position each box in `abs_boxes` (already collected as the absolute
    descendants anchored to one containing block) against the explicit
    containing-block rectangle (cb_x, cb_y, cb_w, cb_h)."""
    for abs_box in abs_boxes:
        style = abs_box.style
        top = style.length("top")
        left = style.length("left")
        right = style.length("right")
        bottom = style.length("bottom")

        _resolve_edges(abs_box, cb_w)
        width_val = style.length("width")
        if width_val.kind == "auto":
            if left.kind != "auto" and right.kind != "auto":
                content_w = max(0.0, cb_w - resolve_len(left, cb_w, 0.0) - resolve_len(right, cb_w, 0.0))
            else:
                content_w = shrink_to_fit_width(abs_box, cb_w)
        else:
            content_w = resolve_len(width_val, cb_w, 0.0)

        x_off = resolve_len(left, cb_w, None)
        if x_off is None:
            r = resolve_len(right, cb_w, None)
            x_off = (cb_w - content_w - r) if r is not None else 0.0
        y_off = resolve_len(top, cb_h, None)

        abs_box.dims.width = content_w
        abs_box.dims.x = cb_x + x_off + abs_box.dims.margin.left
        abs_box.dims.y = cb_y + (y_off if y_off is not None else 0.0) + abs_box.dims.margin.top

        child_cb = ContainingBlock(width=cb_w, height=cb_h)
        layout_box(abs_box, child_cb, viewport, forced_width=content_w)

        if y_off is None:
            btm = resolve_len(bottom, cb_h, None)
            if btm is not None:
                abs_box.dims.y = cb_y + (cb_h - abs_box.dims.height - btm) + abs_box.dims.margin.top


def shrink_to_fit_width(box, available):
    measured = measure_preferred_width(box)
    return max(0.0, min(available, measured))


def measure_preferred_width(box):
    """Approximate max-content width: the width the box would need so that
    none of its content wraps. This can't be measured by laying the box out
    at a huge containing width, because a block box with `width: auto`
    *fills* whatever containing width it's given (that's the CSS rule) --
    at width 1,000,000px it would just report back 1,000,000px. Instead this
    walks the box's own children directly: an explicit CSS width wins
    outright; otherwise a block-level box's preferred width is the widest
    single child it would need to avoid wrapping (children stack), while a
    flex row's is the sum of its items' preferred widths (they sit side by
    side)."""
    if box.box_type == "anonymous-block":
        return natural_text_width(box)
    if box.box_type == "replaced":
        w = box.style.length("width") if box.style else None
        return w.data if (w is not None and w.kind == "px") else 60.0
    style = box.style
    if style is not None:
        width_val = style.length("width")
        if width_val.kind == "px":
            return width_val.data
    children = [c for c in box.children if not isinstance(c, tuple)]
    if not children:
        return 0.0
    if box.box_type == "flex" and style is not None and style.keyword("flex-direction") in ("row", "row-reverse"):
        return sum(measure_preferred_width(c) for c in children)
    return max(measure_preferred_width(c) for c in children)


def natural_text_width(box):
    # Approximates max-content width as the sum of all token widths, which
    # is exact for the common case (no forced <br> in the run); a run
    # containing <br> would ideally use the widest single line instead.
    if box.box_type == "anonymous-block" and box.ifc_items:
        total = 0.0
        for item in box.ifc_items:
            if item[0] == "word":
                _, text, style = item
                total += len(text) * advance_width(style.font_size_px())
            elif item[0] == "space":
                total += advance_width(16.0)
            elif item[0] in ("replaced", "inline-block"):
                total += measure_preferred_width(item[1])
        return total
    return 0.0


# ---------------------------------------------------------------------------
# Inline formatting context (anonymous-block layout)
# ---------------------------------------------------------------------------

class Line:
    __slots__ = ("items", "y", "height")

    def __init__(self):
        self.items = []  # (x, kind, payload, style_or_none, width, height)
        self.y = 0.0
        self.height = 0.0


def layout_anonymous_block(box, cb, viewport):
    max_width = max(0.0, cb.width)
    items = box.ifc_items or []
    style = box.style
    default_h = style.line_height_px() if style else 16.0

    raw_lines = []
    current = []
    current_width = 0.0
    pending_space_width = None

    def push_line():
        nonlocal current, current_width
        raw_lines.append(current)
        current = []
        current_width = 0.0

    for item in items:
        kind = item[0]
        if kind == "break":
            push_line()
            pending_space_width = None
            continue
        if kind == "space":
            ref_style = current[-1][3] if current and current[-1][3] else style
            pending_space_width = advance_width(ref_style.font_size_px() if ref_style else 16.0)
            continue
        if kind == "word":
            _, text, wstyle = item
            w = len(text) * advance_width(wstyle.font_size_px())
            h = wstyle.line_height_px()
            extra = pending_space_width or 0.0 if current else 0.0
            if current and current_width + extra + w > max_width + 0.01:
                push_line()
                extra = 0.0
            x = current_width + extra
            current.append((x, "word", text, wstyle, w, h))
            current_width = x + w
            pending_space_width = None
            continue
        if kind in ("replaced", "inline-block"):
            payload_box = item[1]
            icb = ContainingBlock(width=max_width, height=None)
            payload_box.dims = Dimensions()
            layout_box(payload_box, icb, viewport)
            w = payload_box.dims.width
            h = payload_box.dims.height
            extra = pending_space_width or 0.0 if current else 0.0
            if current and current_width + extra + w > max_width + 0.01:
                push_line()
                extra = 0.0
            x = current_width + extra
            current.append((x, kind, payload_box, None, w, h))
            current_width = x + w
            pending_space_width = None
            continue
    push_line()

    text_align = style.keyword("text-align") if style else "left"
    y = 0.0
    built_lines = []
    for entries in raw_lines:
        h = max((e[5] for e in entries), default=default_h)
        content_width = (entries[-1][0] + entries[-1][4]) if entries else 0.0
        offset = 0.0
        if text_align == "center":
            offset = max(0.0, (max_width - content_width) / 2.0)
        elif text_align == "right":
            offset = max(0.0, max_width - content_width)
        line = Line()
        line.y = y
        line.height = h
        for (x, kind, payload, st, w, ih) in entries:
            line.items.append((offset + x, kind, payload, st, w, ih))
        built_lines.append(line)
        y += h

    box.lines = built_lines
    box.dims.width = max_width
    box.dims.height = y

    # Now that box.dims.x/y are final (set by the caller before this call
    # for block/flex flow -- true for every caller in this module), give
    # replaced/inline-block payload boxes their real absolute position.
    for line in box.lines:
        for (x, kind, payload, st, w, ih) in line.items:
            if kind in ("replaced", "inline-block"):
                translate_box_tree(payload, box.dims.x + x - payload.dims.x, box.dims.y + line.y - payload.dims.y)


def layout_replaced(box, cb):
    style = box.style
    width_val = style.length("width")
    height_val = style.length("height")
    w = resolve_len(width_val, cb.width, 60.0)
    h = resolve_len(height_val, cb.height, 40.0)
    box.dims.width = w
    box.dims.height = h
    _resolve_edges(box, cb.width)


def translate_box_tree(box, dx, dy):
    if dx == 0.0 and dy == 0.0:
        return
    box.dims.x += dx
    box.dims.y += dy
    for child in box.children:
        if isinstance(child, tuple):
            continue
        translate_box_tree(child, dx, dy)
    if box.lines:
        for line in box.lines:
            for (_, kind, payload, _st, _w, _h) in line.items:
                if kind in ("replaced", "inline-block") and payload is not None:
                    translate_box_tree(payload, dx, dy)
    for abs_box in box.absolute_children:
        translate_box_tree(abs_box, dx, dy)


# ---------------------------------------------------------------------------
# Flexbox layout
# ---------------------------------------------------------------------------

def layout_flex(box, cb, viewport, forced_width=None, forced_height=None):
    style = box.style
    d = box.dims
    cw = cb.width
    ml_v, mr_v = _resolve_edges(box, cw)
    width_val = style.length("width")
    edge_w = d.padding.left + d.padding.right + d.border.left + d.border.right
    if forced_width is not None:
        content_w = forced_width
        ml_v = ml_v if ml_v is not None else 0.0
        mr_v = mr_v if mr_v is not None else 0.0
    elif width_val.kind == "auto":
        avail = cw - edge_w
        ml_v = ml_v if ml_v is not None else 0.0
        mr_v = mr_v if mr_v is not None else 0.0
        content_w = max(0.0, avail - ml_v - mr_v)
    else:
        content_w = resolve_len(width_val, cw, 0.0)
        ml_v = ml_v if ml_v is not None else 0.0
        mr_v = mr_v if mr_v is not None else 0.0
    d.margin.left = ml_v
    d.margin.right = mr_v
    d.width = content_w

    direction = style.keyword("flex-direction")
    is_row = direction in ("row", "row-reverse")
    reverse = direction in ("row-reverse", "column-reverse")
    wrap = style.keyword("flex-wrap") == "wrap"

    if forced_height is not None:
        definite_height = forced_height
    else:
        height_val = style.length("height")
        definite_height = None
        if height_val.kind == "px":
            definite_height = height_val.data
        elif height_val.kind == "pct" and cb.height is not None:
            definite_height = height_val.data / 100.0 * cb.height

    items = list(box.children)
    if reverse:
        items = list(reversed(items))

    if not items:
        d.height = definite_height if definite_height is not None else 0.0
        resolve_absolute_children(box, viewport)
        return

    main_size = content_w if is_row else definite_height

    for item in items:
        ml, mr = _resolve_edges(item, content_w)
        # _resolve_edges only *returns* left/right margin (block layout
        # decides separately whether 'auto' means centering); flex has no
        # such ambiguity here, so assign them now -- otherwise every basis/
        # wrap/justify computation below silently treats horizontal
        # margins as zero even though the final per-item layout pass (which
        # does assign them) uses the real value, letting bordered/margined
        # rows overflow their container.
        item.dims.margin.left = ml if ml is not None else 0.0
        item.dims.margin.right = mr if mr is not None else 0.0

    def outer_main_extra(item):
        # Every main-axis edge outside the content box: margin, border, AND
        # padding. flex-basis is a content-box size, so anything comparing
        # basis against the container's main size needs all three, or
        # bordered/padded items silently overflow the wrap/justify math.
        d2 = item.dims
        if is_row:
            return (d2.margin.left + d2.border.left + d2.padding.left
                    + d2.margin.right + d2.border.right + d2.padding.right)
        return (d2.margin.top + d2.border.top + d2.padding.top
                + d2.margin.bottom + d2.border.bottom + d2.padding.bottom)

    def basis_of(item, line_main_size):
        basis_val = item.style.length("flex-basis")
        width_val_i = item.style.length("width")
        height_val_i = item.style.length("height")
        ref = line_main_size if line_main_size is not None else content_w
        if basis_val.kind != "auto":
            return max(0.0, resolve_len(basis_val, ref, 0.0))
        prop = width_val_i if is_row else height_val_i
        if prop.kind != "auto":
            return max(0.0, resolve_len(prop, ref, 0.0))
        if is_row:
            return measure_preferred_width(item)
        return 0.0

    flex_lines = []
    if wrap and main_size is not None:
        cur = []
        cur_main = 0.0
        for item in items:
            b = basis_of(item, main_size) + outer_main_extra(item)
            if cur and cur_main + b > main_size + 0.01:
                flex_lines.append(cur)
                cur = []
                cur_main = 0.0
            cur.append(item)
            cur_main += b
        if cur:
            flex_lines.append(cur)
    else:
        flex_lines = [items]

    cross_pos = 0.0
    justify = style.keyword("justify-content")
    align_items = style.keyword("align-items")

    for line_items in flex_lines:
        basis = {id(it): basis_of(it, main_size) for it in line_items}
        margins = {id(it): outer_main_extra(it) for it in line_items}
        total_basis = sum(basis[id(it)] + margins[id(it)] for it in line_items)
        line_main = main_size if main_size is not None else total_basis
        free_space = line_main - total_basis

        final_main = {}
        if free_space > 0:
            total_grow = sum(it.style.number("flex-grow", 0.0) for it in line_items)
            for it in line_items:
                grow = it.style.number("flex-grow", 0.0)
                extra = (free_space * grow / total_grow) if total_grow > 0 else 0.0
                final_main[id(it)] = basis[id(it)] + extra
        elif free_space < 0:
            total_shrink = sum(it.style.number("flex-shrink", 1.0) * basis[id(it)] for it in line_items)
            for it in line_items:
                shrink = it.style.number("flex-shrink", 1.0) * basis[id(it)]
                reduce_by = (abs(free_space) * shrink / total_shrink) if total_shrink > 0 else 0.0
                final_main[id(it)] = max(0.0, basis[id(it)] - reduce_by)
        else:
            for it in line_items:
                final_main[id(it)] = basis[id(it)]

        # Sizing pass: lay out each item's own subtree with its border-box
        # placed at a placeholder (0, 0) origin -- final position isn't
        # known until every item on this line has been sized (justify-
        # content needs the total). Matches the block-flow contract that
        # dims.x/y are already the box's *content* origin by the time
        # layout_box runs, just against a placeholder instead of the real
        # parent origin.
        for it in line_items:
            fm = final_main[id(it)]
            it.dims = Dimensions()
            _resolve_edges(it, content_w)
            it.dims.x = it.dims.margin.left + it.dims.border.left + it.dims.padding.left
            it.dims.y = it.dims.margin.top + it.dims.border.top + it.dims.padding.top
            if is_row:
                min_w = _px(it.style, "min-width", content_w, 0.0)
                max_w_val = it.style.length("max-width")
                max_w = resolve_len(max_w_val, content_w, None) if max_w_val.kind != "none" else None
                fm = max(fm, min_w)
                if max_w is not None:
                    fm = min(fm, max_w)
                item_cb = ContainingBlock(width=content_w, height=None)
                layout_box(it, item_cb, viewport, forced_width=fm)
            else:
                item_cb = ContainingBlock(width=content_w, height=None)
                layout_box(it, item_cb, viewport, forced_height=fm)
            final_main[id(it)] = fm

        def _outer_cross(it):
            d2 = it.dims
            if is_row:
                return d2.height + d2.margin.top + d2.margin.bottom + d2.border.top + d2.border.bottom + d2.padding.top + d2.padding.bottom
            return d2.width + d2.margin.left + d2.margin.right + d2.border.left + d2.border.right + d2.padding.left + d2.padding.right

        cross_size = max((_outer_cross(it) for it in line_items), default=0.0)
        if is_row and definite_height is not None:
            cross_size = max(cross_size, definite_height)

        used_main = sum(final_main[id(it)] + margins[id(it)] for it in line_items)
        remaining = max(0.0, line_main - used_main)
        n = len(line_items)
        if justify == "center":
            start, gap = remaining / 2.0, 0.0
        elif justify == "flex-end":
            start, gap = remaining, 0.0
        elif justify == "space-between" and n > 1:
            start, gap = 0.0, remaining / (n - 1)
        elif justify == "space-around" and n > 0:
            gap = remaining / n
            start = gap / 2.0
        elif justify == "space-evenly" and n > 0:
            gap = remaining / (n + 1)
            start = gap
        else:
            start, gap = 0.0, 0.0

        pos = start
        for it in line_items:
            fm = final_main[id(it)]
            edge_left = it.dims.margin.left + it.dims.border.left + it.dims.padding.left
            edge_right = it.dims.margin.right + it.dims.border.right + it.dims.padding.right
            edge_top = it.dims.margin.top + it.dims.border.top + it.dims.padding.top
            edge_bottom = it.dims.margin.bottom + it.dims.border.bottom + it.dims.padding.bottom
            if is_row:
                final_x = d.x + pos + edge_left
                cross_align = align_items
                item_cross = it.dims.height + edge_top + edge_bottom
                if cross_align == "stretch" and it.style.length("height").kind == "auto":
                    stretched = definite_height if definite_height is not None else cross_size
                    if stretched > item_cross:
                        content_stretched = max(0.0, stretched - edge_top - edge_bottom)
                        stretch_cb = ContainingBlock(width=content_w, height=None)
                        it.dims = Dimensions()
                        _resolve_edges(it, content_w)
                        it.dims.x = it.dims.margin.left + it.dims.border.left + it.dims.padding.left
                        it.dims.y = it.dims.margin.top + it.dims.border.top + it.dims.padding.top
                        layout_box(it, stretch_cb, viewport, forced_width=fm, forced_height=content_stretched)
                        item_cross = stretched
                if cross_align == "center":
                    final_y = d.y + cross_pos + max(0.0, (cross_size - item_cross) / 2.0) + edge_top
                elif cross_align == "flex-end":
                    final_y = d.y + cross_pos + max(0.0, cross_size - item_cross) + edge_top
                else:
                    final_y = d.y + cross_pos + edge_top
                translate_box_tree(it, final_x - it.dims.x, final_y - it.dims.y)
                apply_relative_offset(it, content_w)
                pos += edge_left + fm + edge_right + gap
            else:
                final_y = d.y + pos + edge_top
                cross_avail = content_w
                item_cross = it.dims.width + edge_left + edge_right
                if align_items == "stretch" and it.style.length("width").kind == "auto" and cross_avail > item_cross:
                    content_stretched = max(0.0, cross_avail - edge_left - edge_right)
                    stretch_cb = ContainingBlock(width=cross_avail, height=None)
                    it.dims = Dimensions()
                    _resolve_edges(it, content_w)
                    it.dims.x = it.dims.margin.left + it.dims.border.left + it.dims.padding.left
                    it.dims.y = it.dims.margin.top + it.dims.border.top + it.dims.padding.top
                    layout_box(it, stretch_cb, viewport, forced_width=content_stretched, forced_height=fm)
                    item_cross = it.dims.width + edge_left + edge_right
                if align_items == "center":
                    final_x = d.x + cross_pos + max(0.0, (cross_size - item_cross) / 2.0) + edge_left
                elif align_items == "flex-end":
                    final_x = d.x + cross_pos + max(0.0, cross_size - item_cross) + edge_left
                else:
                    final_x = d.x + cross_pos + edge_left
                translate_box_tree(it, final_x - it.dims.x, final_y - it.dims.y)
                apply_relative_offset(it, content_w)
                pos += edge_top + fm + edge_bottom + gap

        cross_pos += cross_size

    if is_row:
        d.height = definite_height if definite_height is not None else cross_pos
    else:
        d.height = main_size if main_size is not None else sum(
            (basis_of(it, None) + outer_main_extra(it)) for it in items
        )

    resolve_absolute_children(box, viewport)
