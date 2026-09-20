"""The box-model layout engine: turns a DOM + computed-style map into a tree
of positioned, sized boxes (in real pixels) ready to paint.

Text is measured and wrapped on a fixed-pitch (monospace) character grid —
see PLAN.md's "Honest scope boundaries." That single decision is what lets
every width/height number below be exact integer arithmetic instead of a
guess at real glyph metrics.
"""

import re

from .dom import Element, Text

CHAR_WIDTH_RATIO = 0.6
LINE_HEIGHT_RATIO = 1.2
DEFAULT_VIEWPORT_WIDTH = 800

_LENGTH_RE = re.compile(r"^(-?[0-9]*\.?[0-9]+)(px|%)?$")

_SIDES = ("top", "right", "bottom", "left")


def char_width(font_size_px):
    return max(1, round(font_size_px * CHAR_WIDTH_RATIO))


def line_height_px(font_size_px):
    return max(1, round(font_size_px * LINE_HEIGHT_RATIO))


def parse_length(value, percent_base):
    """Resolve a CSS length/percentage/auto string to a pixel int, or the
    string 'auto'. `percent_base` may be None if percentages can't resolve
    here yet (treated as 0, the same conservative fallback real browsers use
    for an indefinite containing block)."""
    if value is None:
        return 0
    value = value.strip()
    if value == "auto":
        return "auto"
    m = _LENGTH_RE.match(value)
    if not m:
        return 0
    number = float(m.group(1))
    unit = m.group(2)
    if unit == "%":
        base = percent_base or 0
        return round(base * number / 100)
    return round(number)


def parse_nonneg_length(value, percent_base):
    result = parse_length(value, percent_base)
    if result == "auto":
        return 0
    return max(0, result)


class Box:
    """One box in the layout tree: border-box position/size + the three
    box-model edges around it, plus paint-relevant style."""

    def __init__(self, node, style, box_type):
        self.node = node          # DOM Element, or None for anonymous boxes
        self.style = style        # ComputedStyle, or None for anonymous
        self.box_type = box_type  # 'block' | 'anon-block' | 'line'
        self.children = []
        self.x = 0
        self.y = 0
        self.width = 0            # border-box width
        self.height = 0           # border-box height
        self.margin = {s: 0 for s in _SIDES}
        self.border = {s: 0 for s in _SIDES}
        self.padding = {s: 0 for s in _SIDES}
        self.float_side = "none"

    @property
    def content_x(self):
        return self.x + self.border["left"] + self.padding["left"]

    @property
    def content_y(self):
        return self.y + self.border["top"] + self.padding["top"]

    @property
    def content_width(self):
        return max(
            0,
            self.width
            - self.border["left"] - self.border["right"]
            - self.padding["left"] - self.padding["right"],
        )

    @property
    def content_height(self):
        return max(
            0,
            self.height
            - self.border["top"] - self.border["bottom"]
            - self.padding["top"] - self.padding["bottom"],
        )

    @property
    def margin_box_left(self):
        return self.x - self.margin["left"]

    @property
    def margin_box_top(self):
        return self.y - self.margin["top"]

    @property
    def margin_box_width(self):
        return self.width + self.margin["left"] + self.margin["right"]

    @property
    def margin_box_height(self):
        return self.height + self.margin["top"] + self.margin["bottom"]

    def __repr__(self):
        label = self.node.tag if isinstance(self.node, Element) else self.box_type
        return f"Box({label} @{self.x},{self.y} {self.width}x{self.height})"


class TextRun:
    """One laid-out, unbreakable chunk of text inside a line box."""

    __slots__ = ("node", "style", "text", "x", "y", "width", "height")

    def __init__(self, node, style, text, x, y, width, height):
        self.node = node
        self.style = style
        self.text = text
        self.x = x
        self.y = y
        self.width = width
        self.height = height


class InlineBox:
    """An atomic inline-level replaced box (currently just <img>) placed on
    a line, sized either from style width/height or a small default."""

    __slots__ = ("node", "style", "x", "y", "width", "height")

    def __init__(self, node, style, x, y, width, height):
        self.node = node
        self.style = style
        self.x = x
        self.y = y
        self.width = width
        self.height = height


# ---------------------------------------------------------------------
# Float placement
# ---------------------------------------------------------------------

class FloatContext:
    """Tracks active floats within one block formatting context. Same-side
    floats stack strictly vertically (a documented scope simplification —
    see PLAN.md); left and right floats are independent, so text can flow
    in the gap between a left float and a right float, which is the
    visually-important case this feature is about."""

    def __init__(self, left_edge, right_edge):
        self.left_edge = left_edge
        self.right_edge = right_edge
        self.left_floats = []
        self.right_floats = []

    def place(self, side, width, height, min_y):
        stack = self.left_floats if side == "left" else self.right_floats
        y = min_y
        if stack:
            y = max(y, stack[-1]["bottom"])
        if side == "left":
            x = self.left_edge
            stack.append({"top": y, "bottom": y + height, "edge": x + width})
        else:
            x = self.right_edge - width
            stack.append({"top": y, "bottom": y + height, "edge": x})
        return x, y

    def available_range(self, y, height):
        left = self.left_edge
        right = self.right_edge
        for f in self.left_floats:
            if f["top"] < y + height and f["bottom"] > y:
                left = max(left, f["edge"])
        for f in self.right_floats:
            if f["top"] < y + height and f["bottom"] > y:
                right = min(right, f["edge"])
        return left, right

    def lowest_bottom(self, side):
        y = 0
        floats = []
        if side in ("left", "both"):
            floats += self.left_floats
        if side in ("right", "both"):
            floats += self.right_floats
        for f in floats:
            y = max(y, f["bottom"])
        return y

    def bottom(self):
        return self.lowest_bottom("both")


# ---------------------------------------------------------------------
# Box-tree construction (DOM + styles -> unpositioned Box skeleton)
# ---------------------------------------------------------------------

class BoxTreeNode:
    """Intermediate tree used only to group inline runs into anonymous
    block wrappers before real layout begins."""

    def __init__(self, node, style, display):
        self.node = node
        self.style = style
        self.display = display  # 'block' | 'inline' | 'text'
        self.block_children = []       # list[BoxTreeNode] (display=='block')
        self.inline_children = []      # list[BoxTreeNode] (display in inline/text)


def _display_of(node, styles):
    if isinstance(node, Text):
        return "text"
    if isinstance(node, Element):
        style = styles.get(node)
        if style is None:
            return "none"
        return style.get("display")
    return "none"


def build_tree_node(element, styles):
    style = styles[element]
    tnode = TreeBuildState(element, style)
    for child in element.children:
        if isinstance(child, Text):
            # Whitespace-only text sitting between block-level children is
            # dropped later, in TreeBuildState.finish(), once we know
            # whether it ended up alone in its own inline group.
            tnode.add_text(child)
        elif isinstance(child, Element):
            disp = _display_of(child, styles)
            if disp == "none":
                continue
            if disp == "block":
                tnode.add_block(build_tree_node(child, styles))
            else:
                tnode.add_inline_element(child, styles)
    return tnode.finish()


class TreeBuildState:
    """Builds one element's children into block boxes + anonymous-block-
    wrapped inline runs, in document order."""

    def __init__(self, element, style):
        self.element = element
        self.style = style
        self.groups = []          # list of ('block', BoxTreeNode) | ('inline', list)
        self._current_inline = None

    def _inline_group(self):
        if self._current_inline is None:
            self._current_inline = []
            self.groups.append(("inline", self._current_inline))
        return self._current_inline

    def add_text(self, text_node):
        if text_node.data == "":
            return
        self._inline_group().append(("text", text_node, self.style))

    def add_block(self, child_tnode):
        self._current_inline = None
        self.groups.append(("block", child_tnode))

    def add_inline_element(self, element, styles):
        style = styles[element]
        self._flatten_inline(element, style, styles, self._inline_group())

    def _flatten_inline(self, element, style, styles, out):
        if element.tag == "img":
            out.append(("img", element, style))
            return
        if element.tag == "br":
            out.append(("br", element, style))
            return
        for child in element.children:
            if isinstance(child, Text):
                if child.data != "":
                    out.append(("text", child, style))
            elif isinstance(child, Element):
                disp = _display_of(child, styles)
                if disp == "none":
                    continue
                if disp == "block":
                    # A block inside an inline ancestor: rare, but don't
                    # crash -- flush it into the surrounding flow as its
                    # own block-level box (browsers do something similar).
                    self._current_inline = None
                    self.groups.append(("block", build_tree_node(child, styles)))
                    self._inline_group()
                else:
                    self._flatten_inline(child, styles[child], styles, out)

    def finish(self):
        tnode = BoxTreeNode(self.element, self.style, "block")
        for kind, payload in self.groups:
            if kind == "block":
                tnode.block_children.append(("block", payload))
            else:
                if any(
                    item[0] != "text" or item[1].data.strip() != ""
                    for item in payload
                ):
                    tnode.block_children.append(("inline", payload))
        return tnode


# ---------------------------------------------------------------------
# Layout proper
# ---------------------------------------------------------------------

def _resolve_box_model(style, containing_block_width):
    margin = {}
    border = {}
    padding = {}
    for side in _SIDES:
        margin[side] = parse_length(style.get(f"margin-{side}"), containing_block_width)
        border_style = style.get(f"border-{side}-style")
        if border_style == "none":
            border[side] = 0
        else:
            border[side] = parse_nonneg_length(
                style.get(f"border-{side}-width"), containing_block_width
            )
        padding[side] = parse_nonneg_length(
            style.get(f"padding-{side}"), containing_block_width
        )
    return margin, border, padding


def _resolve_width(style, containing_block_width, border, padding):
    specified = style.get("width")
    width = parse_length(specified, containing_block_width)
    box_sizing = style.get("box-sizing")
    if width != "auto" and box_sizing == "border-box":
        width = max(0, width - border["left"] - border["right"] - padding["left"] - padding["right"])
    return width


def layout_document(document, styles, viewport_width=DEFAULT_VIEWPORT_WIDTH):
    """Entry point: lay out the whole document. Returns the root Box (for
    <html>), positioned with (0, 0) at the top-left of the viewport."""
    html_element = None
    for child in document.children:
        if isinstance(child, Element):
            html_element = child
            break
    if html_element is None:
        root = Box(None, None, "block")
        root.width = viewport_width
        return root

    tree = build_tree_node(html_element, styles)
    root_box = Box(tree.node, tree.style, "block")
    layout_block(root_box, tree, containing_block_width=viewport_width,
                 containing_block_height=None, x=0, y=0)
    return root_box


def _default_anon_style(parent_style):
    """Anonymous boxes (inline-wrapper blocks) have no own style, but their
    box model is all-zero and they inherit text properties from the parent
    for their line boxes to use."""
    return parent_style


def layout_block(box, tnode, containing_block_width, containing_block_height, x, y):
    """Lay out `box` (already created, with .node/.style/.box_type set) as
    a block-level box whose border-box top-left is (x, y)."""
    style = tnode.style
    margin, border, padding = _resolve_box_model(style, containing_block_width)
    # `margin: auto` only has special meaning for the left/right edges of a
    # block-level box; a top/bottom `auto` always computes to 0.
    if margin["top"] == "auto":
        margin["top"] = 0
    if margin["bottom"] == "auto":
        margin["bottom"] = 0
    width = _resolve_width(style, containing_block_width, border, padding)

    box.margin = margin
    box.border = border
    box.padding = padding

    content_box_left = border["left"] + padding["left"]
    content_box_right = border["right"] + padding["right"]

    if width == "auto":
        margin_left = 0 if margin["left"] == "auto" else margin["left"]
        margin_right = 0 if margin["right"] == "auto" else margin["right"]
        width = max(
            0,
            containing_block_width - margin_left - margin_right
            - content_box_left - content_box_right,
        )
        box.margin["left"] = margin_left
        box.margin["right"] = margin_right
    else:
        used_left = margin["left"]
        used_right = margin["right"]
        remaining = containing_block_width - (content_box_left + width + content_box_right)
        if used_left == "auto" and used_right == "auto":
            half = max(0, remaining) // 2
            used_left, used_right = half, max(0, remaining) - half
        elif used_left == "auto":
            used_left = remaining - used_right
        elif used_right == "auto":
            used_right = remaining - used_left
        else:
            # Over-constrained (width + both margins all specified): per
            # CSS2.1 10.3.3, the specified margin-right is ignored and
            # solved for instead (LTR), not averaged with the remainder.
            used_right = remaining - used_left
        box.margin["left"] = used_left
        box.margin["right"] = used_right

    box.width = content_box_left + width + content_box_right
    box.x = x
    box.y = y

    content_width = width
    float_ctx = FloatContext(box.content_x, box.content_x + content_width)

    cursor = box.content_y
    prev_margin_bottom = 0
    first = True

    for kind, payload in tnode.block_children:
        if kind == "inline":
            line_box_container = layout_inline_children(
                payload, box.content_x, cursor, content_width, float_ctx, style
            )
            box.children.append(line_box_container)
            cursor = line_box_container.y + line_box_container.height
            prev_margin_bottom = 0
            first = False
            continue

        child_tnode = payload
        child_style = child_tnode.style
        child_float = child_style.get("float")
        child_clear = child_style.get("clear")

        if child_clear != "none":
            cursor = max(cursor, box.content_y + float_ctx.lowest_bottom(child_clear))

        if child_float != "none":
            child_box = Box(child_tnode.node, child_style, "block")
            _layout_float_child(child_box, child_tnode, content_width, cursor, float_ctx, box.content_x, content_width)
            box.children.append(child_box)
            continue

        child_margin, child_border, child_padding = _resolve_box_model(
            child_style, content_width
        )
        child_top_margin = 0 if child_margin["top"] == "auto" else child_margin["top"]
        gap = child_top_margin if first else max(child_top_margin, prev_margin_bottom)

        child_box = Box(child_tnode.node, child_style, "block")
        layout_block(
            child_box, child_tnode,
            containing_block_width=content_width,
            containing_block_height=None,
            x=box.content_x, y=cursor + gap,
        )
        box.children.append(child_box)
        cursor = child_box.y + child_box.height
        prev_margin_bottom = 0 if child_margin["bottom"] == "auto" else child_margin["bottom"]
        first = False

    content_bottom = max(cursor + prev_margin_bottom, box.content_y + float_ctx.bottom())
    auto_content_height = max(0, content_bottom - box.content_y)

    height_spec = style.get("height")
    height = parse_length(height_spec, containing_block_height)
    if height == "auto":
        content_height = auto_content_height
    else:
        content_height = height
        if style.get("box-sizing") == "border-box":
            content_height = max(
                0, content_height - border["top"] - border["bottom"] - padding["top"] - padding["bottom"]
            )

    box.height = content_height + border["top"] + border["bottom"] + padding["top"] + padding["bottom"]


def _layout_float_child(child_box, child_tnode, containing_block_width, min_y, float_ctx, cb_left, cb_width):
    style = child_tnode.style
    margin, border, padding = _resolve_box_model(style, containing_block_width)
    width = _resolve_width(style, containing_block_width, border, padding)
    child_box.margin = {s: (0 if margin[s] == "auto" else margin[s]) for s in _SIDES}
    child_box.border = border
    child_box.padding = padding

    content_left = border["left"] + padding["left"]
    content_right = border["right"] + padding["right"]

    if width == "auto":
        width = _shrink_to_fit_width(child_tnode, containing_block_width)

    box_width = content_left + width + content_right
    child_box.width = box_width

    side = style.get("float")
    outer_x, outer_y = float_ctx.place(side, box_width + child_box.margin["left"] + child_box.margin["right"], 1, min_y)
    child_box.x = outer_x + child_box.margin["left"]
    child_box.y = outer_y + child_box.margin["top"]
    child_box.float_side = side

    # Lay out the float's own children against its resolved width, then
    # correct its placement height in the float context (a float's height
    # depends on its content, discovered only after layout).
    inner_ctx = FloatContext(child_box.content_x, child_box.content_x + width)
    cursor = child_box.content_y
    prev_margin_bottom = 0
    first = True
    for kind, payload in child_tnode.block_children:
        if kind == "inline":
            line_container = layout_inline_children(
                payload, child_box.content_x, cursor, width, inner_ctx, style
            )
            child_box.children.append(line_container)
            cursor = line_container.y + line_container.height
            prev_margin_bottom = 0
            first = False
            continue
        grandchild_style = payload.style
        gmargin, gborder, gpadding = _resolve_box_model(grandchild_style, width)
        top_m = 0 if gmargin["top"] == "auto" else gmargin["top"]
        gap = top_m if first else max(top_m, prev_margin_bottom)
        grandchild_box = Box(payload.node, grandchild_style, "block")
        layout_block(grandchild_box, payload, containing_block_width=width,
                     containing_block_height=None, x=child_box.content_x, y=cursor + gap)
        child_box.children.append(grandchild_box)
        cursor = grandchild_box.y + grandchild_box.height
        prev_margin_bottom = 0 if gmargin["bottom"] == "auto" else gmargin["bottom"]
        first = False

    content_height = max(0, cursor + prev_margin_bottom - child_box.content_y)
    height_spec = style.get("height")
    height = parse_length(height_spec, None)
    if height != "auto":
        content_height = height
    child_box.height = content_height + border["top"] + border["bottom"] + padding["top"] + padding["bottom"]

    # Now that we know the real height, update the float record we placed
    # with a provisional height of 1px.
    stack = float_ctx.left_floats if side == "left" else float_ctx.right_floats
    stack[-1]["bottom"] = stack[-1]["top"] + child_box.margin_box_height


def _shrink_to_fit_width(tnode, available_width):
    """A rough shrink-to-fit: the widest line of any inline content, or the
    available width if the box contains block children (blocks always
    claim full available width in this engine's normal-flow algorithm)."""
    max_line_chars = 0
    has_block = False
    for kind, payload in tnode.block_children:
        if kind == "block":
            has_block = True
        else:
            words = []
            for item_kind, node, style in payload:
                if item_kind == "text":
                    words.extend(node.data.split())
            line = " ".join(words)
            max_line_chars = max(max_line_chars, len(line))
    if has_block:
        return available_width
    font_size = parse_length(tnode.style.get("font-size"), None)
    cw = char_width(font_size if isinstance(font_size, int) else 16)
    return min(available_width, max_line_chars * cw)


# ---------------------------------------------------------------------
# Inline layout: word-wrapping text (+ inline atoms) into line boxes
# ---------------------------------------------------------------------

def _collect_inline_items(payload):
    """Flatten (kind, node, style) triples into word-level items, collapsing
    whitespace the way CSS `white-space: normal` does -- including
    whitespace that falls *between* two DOM nodes (e.g. "Hello <b>world</b>"
    must keep the space; "Hello<b>world</b>" must not gain one)."""
    items = []
    pending_space = False
    started = False
    for kind, node, style in payload:
        if kind == "text":
            data = node.data
            if data == "":
                continue
            if data[0].isspace() and started:
                pending_space = True
            words = data.split()
            for i, word in enumerate(words):
                # A word after the first one *within this same text node*
                # was, by definition, separated by internal whitespace that
                # str.split() just ate -- put a space back between them.
                if pending_space or i > 0:
                    items.append(("space", None, style, node))
                    pending_space = False
                items.append(("word", word, style, node))
                started = True
            if data[-1].isspace() and started:
                pending_space = True
        elif kind == "img":
            if pending_space:
                items.append(("space", None, style, node))
                pending_space = False
            items.append(("img", node, style, node))
            started = True
        elif kind == "br":
            items.append(("break", None, style, node))
            pending_space = False
            started = True
    return items


def layout_inline_children(payload, x, y, available_width, float_ctx, container_style):
    """Lay out one anonymous inline-formatting-context block: wraps text +
    inline atoms into line boxes, returns the anonymous container Box."""
    container = Box(None, container_style, "anon-block")
    container.x = x
    container.y = y
    container.width = available_width

    items = _collect_inline_items(payload)
    text_align = container_style.get("text-align")

    line_y = y
    idx = 0
    n = len(items)

    while idx < n:
        # Skip a leading space at the start of a line.
        if items[idx][0] == "space":
            idx += 1
            continue
        if idx >= n:
            break

        probe_height = line_height_px(
            parse_length(items[idx][2].get("font-size"), None) or 16
        )
        left_bound, right_bound = float_ctx.available_range(line_y, probe_height)
        line_available = max(0, right_bound - left_bound)

        run_items = []
        cursor_chars_width = 0
        line_height = 0
        first_word_on_line = True

        while idx < n:
            kind, value, style, node = items[idx]
            font_size = parse_length(style.get("font-size"), None) or 16
            cw = char_width(font_size)
            lh = line_height_px(font_size)

            if kind == "break":
                idx += 1
                break

            if kind == "space":
                if first_word_on_line:
                    idx += 1
                    continue
                space_width = cw
                if cursor_chars_width + space_width > line_available and run_items:
                    break
                run_items.append((kind, value, style, node, space_width))
                cursor_chars_width += space_width
                idx += 1
                continue

            if kind == "word":
                word_width = len(value) * cw
            elif kind == "img":
                img_w = parse_length(style.get("width"), None)
                word_width = img_w if isinstance(img_w, int) else cw * 4
            else:
                word_width = 0

            if not first_word_on_line and cursor_chars_width + word_width > line_available:
                break

            run_items.append((kind, value, style, node, word_width))
            cursor_chars_width += word_width
            line_height = max(line_height, lh)
            first_word_on_line = False
            idx += 1

        if not run_items:
            # A single word wider than the whole line: place it anyway so
            # we always make forward progress.
            kind, value, style, node = items[idx]
            font_size = parse_length(style.get("font-size"), None) or 16
            cw = char_width(font_size)
            lh = line_height_px(font_size)
            width = len(value) * cw if kind == "word" else cw * 4
            run_items = [(kind, value, style, node, width)]
            line_height = lh
            idx += 1

        # Trim a trailing space from the line.
        while run_items and run_items[-1][0] == "space":
            run_items.pop()

        line_box = Box(None, container_style, "line")
        content_width = sum(w for *_, w in run_items)
        line_box.width = max(0, right_bound - left_bound)
        line_box.height = line_height or line_height_px(16)
        line_box.y = line_y

        if text_align == "center":
            start_x = left_bound + max(0, (line_box.width - content_width) // 2)
        elif text_align == "right":
            start_x = left_bound + max(0, line_box.width - content_width)
        else:
            start_x = left_bound
        line_box.x = left_bound

        cx = start_x
        for kind, value, style, node, w in run_items:
            font_size = parse_length(style.get("font-size"), None) or 16
            lh = line_height_px(font_size)
            if kind == "word":
                line_box.children.append(TextRun(node, style, value, cx, line_y, w, lh))
            elif kind == "img":
                img_h = parse_length(style.get("height"), None)
                h = img_h if isinstance(img_h, int) else lh
                line_box.children.append(InlineBox(node, style, cx, line_y, w, h))
            cx += w

        container.children.append(line_box)
        line_y += line_box.height

    container.height = max(0, line_y - y)
    if not container.children:
        container.height = 0
    return container
